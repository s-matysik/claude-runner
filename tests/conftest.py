"""A fake `claude` executable: prints canned output, never touches the network.

The script serves scenarios from a queue in $FAKE_CLAUDE_DIR: scenario N is
the Nth call (the last one repeats). Each scenario is a JSON file with
optional keys: stdout, stderr, exit, sleep. The argv of every call is
appended to calls.log.
"""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest

SCRIPT = """#!{python}
import json, os, sys, time
d = os.environ["FAKE_CLAUDE_DIR"]
cf = os.path.join(d, "counter")
n = int(open(cf).read()) if os.path.exists(cf) else 0
open(cf, "w").write(str(n + 1))
with open(os.path.join(d, "calls.log"), "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
files = sorted(f for f in os.listdir(d) if f.startswith("scenario_"))
sc = json.load(open(os.path.join(d, files[min(n, len(files) - 1)])))
time.sleep(sc.get("sleep", 0))
sys.stdout.write(sc.get("stdout", ""))
sys.stderr.write(sc.get("stderr", ""))
sys.exit(sc.get("exit", 0))
"""


def ok_json(**over):
    data = {
        "type": "result",
        "is_error": False,
        "result": "hello",
        "total_cost_usd": 0.5,
        "session_id": "sess-1",
        "num_turns": 2,
        "duration_ms": 5000,
        "duration_api_ms": 4000,
        "usage": {
            "input_tokens": 10,
            "cache_read_input_tokens": 30000,
            "cache_creation_input_tokens": 0,
            "output_tokens": 400,
        },
        "permission_denials": [],
    }
    data.update(over)
    return data


class Fake:
    def __init__(self, path):
        self.dir = path
        self.bin = str(path / "claude")
        self.env = {**os.environ, "FAKE_CLAUDE_DIR": str(path)}
        self._count = 0

    def script(self, *scenarios):
        for i, sc in enumerate(scenarios):
            (self.dir / f"scenario_{i:02d}.json").write_text(json.dumps(sc))

    def calls(self):
        log = self.dir / "calls.log"
        if not log.exists():
            return []
        return [json.loads(x) for x in log.read_text().splitlines()]


@pytest.fixture
def fake(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    exe = d / "claude"
    exe.write_text(SCRIPT.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return Fake(d)
