import json

from conftest import ok_json

from claude_runner import ClaudeRunner


def make(fake, **kw):
    return ClaudeRunner(claude_bin=fake.bin, env=fake.env, **kw)


def test_success_parses_fields(fake):
    fake.script({"stdout": json.dumps(ok_json(permission_denials=[{"tool_name": "Bash"}]))})
    res = make(fake).run("hi")
    assert res.ok and res.output_text == "hello"
    assert res.cost_usd == 0.5 and res.session_id == "sess-1"
    assert res.num_turns == 2 and res.duration_ms == 5000 and res.duration_api_ms == 4000
    assert res.usage["output_tokens"] == 400
    assert res.permission_denials == [{"tool_name": "Bash"}]
    assert res.raw["type"] == "result"


def test_default_args_are_safe(fake):
    fake.script({"stdout": json.dumps(ok_json())})
    make(fake).run("hi")
    argv = fake.calls()[0]
    assert "--permission-mode" not in argv
    assert "bypassPermissions" not in argv
    assert argv[:2] == ["-p", "hi"] and "--output-format" in argv


def test_flags_passed(fake):
    fake.script({"stdout": json.dumps(ok_json())})
    make(
        fake,
        model="sonnet",
        max_turns=3,
        permission_mode="plan",
        allowed_tools=["Read", "Grep"],
        extra_args=["--verbose"],
    ).run("hi")
    argv = fake.calls()[0]
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--max-turns") + 1] == "3"
    assert argv[argv.index("--permission-mode") + 1] == "plan"
    assert argv[argv.index("--allowedTools") + 1] == "Read,Grep"
    assert argv[-1] == "--verbose"


def test_leading_junk_is_tolerated(fake):
    fake.script({"stdout": "warning: something\n" + json.dumps(ok_json())})
    assert make(fake).run("hi").ok


def test_is_error_result(fake):
    fake.script({"stdout": json.dumps(ok_json(is_error=True, result="boom")), "exit": 1})
    res = make(fake).run("hi")
    assert not res.ok and res.error == "boom" and res.error_kind == "claude_error"


def test_rate_limit_in_error_result(fake):
    fake.script({"stdout": json.dumps(ok_json(is_error=True, result="Usage limit reached"))})
    assert make(fake).run("hi").error_kind == "rate_limit"


def test_rate_limit_in_stderr_unparseable(fake):
    fake.script({"stdout": "", "stderr": "429 Too Many Requests: rate limit", "exit": 1})
    res = make(fake).run("hi")
    assert not res.ok and res.error_kind == "rate_limit"


def test_parse_error(fake):
    fake.script({"stdout": "not json", "exit": 1})
    res = make(fake).run("hi")
    assert not res.ok and res.error_kind == "parse_error"
    assert res.raw["returncode"] == 1


def test_timeout(fake):
    fake.script({"stdout": json.dumps(ok_json()), "sleep": 5})
    res = make(fake, timeout_s=0.5).run("hi")
    assert not res.ok and res.error_kind == "timeout"


def test_missing_binary(tmp_path):
    res = ClaudeRunner(claude_bin=str(tmp_path / "nope")).run("hi")
    assert not res.ok and res.error_kind == "runner_unavailable"


def test_log_path_writes_jsonl(fake, tmp_path):
    fake.script({"stdout": json.dumps(ok_json())})
    log = tmp_path / "logs" / "runs.jsonl"
    r = make(fake, log_path=log)
    r.run("a")
    r.run("b")
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(lines) == 2 and lines[0]["duration_api_ms"] == 4000 and lines[0]["ok"] is True


def test_bare_429_is_not_rate_limit():
    from claude_runner import detect_rate_limit

    assert not detect_rate_limit("error at line 429")
    assert not detect_rate_limit("the server is overloaded with requests")
    assert detect_rate_limit("HTTP 429")
    assert detect_rate_limit("429 Too Many Requests")
    assert detect_rate_limit('{"type": "overloaded_error"}')
    assert detect_rate_limit("rate_limit_error")


def test_parse_failure_with_line_429_is_parse_error(fake):
    fake.script({"stdout": "", "stderr": "syntax error at line 429", "exit": 1})
    assert make(fake).run("hi").error_kind == "parse_error"


def test_keyboard_interrupt_kills_child_and_reraises(fake, monkeypatch):
    import os
    import subprocess

    import pytest

    fake.script({"stdout": json.dumps(ok_json()), "sleep": 30})
    seen = {}
    real = subprocess.Popen.communicate

    def interrupted(self, *a, **kw):
        if "pid" not in seen:
            seen["pid"] = self.pid
            raise KeyboardInterrupt
        return real(self, *a, **kw)

    monkeypatch.setattr(subprocess.Popen, "communicate", interrupted)
    runner = make(fake)
    with pytest.raises(KeyboardInterrupt):
        runner.run("hi")
    with pytest.raises(ProcessLookupError):
        os.killpg(seen["pid"], 0)
    assert runner._process is None
