"""Subprocess wrapper around `claude -p <prompt> --output-format json`."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .result import RunResult, detect_rate_limit

DEFAULT_TIMEOUT_S = 600.0


def extract_json(stdout: str | None) -> dict[str, Any] | None:
    """Parse the result object from stdout, tolerating leading junk lines."""
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    lines = text.splitlines()
    for i in range(len(lines)):
        candidate = "\n".join(lines[i:]).strip()
        if not candidate.startswith("{"):
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return parsed if isinstance(parsed, dict) else None
    return None


class ClaudeRunner:
    """Runs the Claude Code CLI in print mode and returns a `RunResult`.

    `permission_mode=None` passes no `--permission-mode` flag, so the CLI's
    own default applies and tools that need approval are denied in `-p` mode.
    `"bypassPermissions"` is available but strictly opt-in: it lets the model
    run any tool without asking. Only use it in a sandbox you trust.

    `run` never raises for CLI failures; inspect `result.ok` and
    `result.error_kind`. A custom `claude_bin` is useful for tests.
    """

    def __init__(
        self,
        model: str | None = None,
        max_turns: int | None = None,
        permission_mode: str | None = None,
        allowed_tools: Sequence[str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        extra_args: Sequence[str] | None = None,
        claude_bin: str = "claude",
        env: dict[str, str] | None = None,
        log_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.model = model
        self.max_turns = max_turns
        self.permission_mode = permission_mode
        self.allowed_tools = list(allowed_tools) if allowed_tools else None
        self.cwd = cwd
        self.timeout_s = timeout_s
        self.extra_args = list(extra_args or [])
        self.claude_bin = claude_bin
        self.env = env
        self.log_path = Path(log_path) if log_path else None
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def build_cmd(self, prompt: str) -> list[str]:
        cmd = [self.claude_bin, "-p", prompt, "--output-format", "json"]
        if self.model:
            cmd += ["--model", self.model]
        if self.max_turns is not None:
            cmd += ["--max-turns", str(self.max_turns)]
        if self.permission_mode:
            cmd += ["--permission-mode", self.permission_mode]
        if self.allowed_tools:
            cmd += ["--allowedTools", ",".join(self.allowed_tools)]
        return cmd + self.extra_args

    def kill(self) -> None:
        """Kill the in-flight run, if any (safe to call from another thread)."""
        with self._lock:
            process = self._process
        if process is not None:
            self._killpg(process)

    @staticmethod
    def _killpg(process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def run(self, prompt: str) -> RunResult:
        result = self._execute(prompt)
        self._log(result)
        return result

    def _execute(self, prompt: str) -> RunResult:
        env = dict(os.environ if self.env is None else self.env)
        try:
            process = subprocess.Popen(
                self.build_cmd(prompt),
                cwd=str(self.cwd) if self.cwd else None,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except (FileNotFoundError, PermissionError) as exc:
            return RunResult(
                ok=False,
                error=f"cannot start {self.claude_bin!r}: {exc}",
                error_kind="runner_unavailable",
            )
        with self._lock:
            self._process = process
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._killpg(process)
            stdout, stderr = process.communicate()
        except KeyboardInterrupt:
            # Do not leave the child (and anything it spawned) running.
            self._killpg(process)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            raise
        finally:
            with self._lock:
                self._process = None

        raw_fail = {"stdout": stdout, "stderr": stderr, "returncode": process.returncode}
        if timed_out:
            return RunResult(
                ok=False,
                error=f"timed out after {self.timeout_s}s",
                error_kind="timeout",
                raw=raw_fail,
            )
        parsed = extract_json(stdout)
        combined = f"{stdout}\n{stderr}"
        if parsed is None:
            return RunResult(
                ok=False,
                error=f"could not parse JSON output from claude (exit code {process.returncode})",
                error_kind="rate_limit" if detect_rate_limit(combined) else "parse_error",
                raw=raw_fail,
            )
        result = RunResult.from_json(parsed)
        if not result.ok:
            if detect_rate_limit(f"{combined} {result.error or ''}"):
                result.error_kind = "rate_limit"
            else:
                result.error_kind = "claude_error"
        return result

    def _log(self, result: RunResult) -> None:
        if self.log_path is None:
            return
        record = dict(result.raw)
        record["logged_at"] = time.time()
        record["ok"] = result.ok
        if result.error_kind:
            record["error_kind"] = result.error_kind
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass
