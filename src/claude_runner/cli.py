"""`claude-runner-report runs.jsonl`: print the timing table."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from . import timing


def load_jsonl(path: str) -> list[dict]:
    runs: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                runs.append(obj)
    return runs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claude-runner-report", description="Timing report from a JSONL file of raw results."
    )
    parser.add_argument("path", help="JSONL file written by ClaudeRunner(log_path=...)")
    args = parser.parse_args(argv)
    try:
        runs = load_jsonl(args.path)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(timing.report(runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
