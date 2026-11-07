import json

import pytest
from conftest import ok_json

from claude_runner import (
    ClaudeRunner,
    CostCapExceeded,
    CostGuard,
    RunResult,
    classify_failure,
    run_with_retry,
)


def fail(kind=None, error=""):
    return RunResult(ok=False, error=error, error_kind=kind)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (fail("timeout"), "transient"),
        (fail("rate_limit"), "rate_limit"),
        (fail("runner_unavailable"), "missing_input"),
        (fail(None, "HTTP 503 service unavailable"), "transient"),
        (fail("claude_error", "Usage limit reached"), "rate_limit"),
        (fail("claude_error", "the model refused"), "defect"),
        (fail("parse_error"), "defect"),
    ],
)
def test_classify_result(result, expected):
    assert classify_failure(result) == expected


def test_classify_exception():
    assert classify_failure(TimeoutError("x")) == "transient"
    assert classify_failure(ConnectionResetError("x")) == "transient"
    assert classify_failure(FileNotFoundError("claude")) == "missing_input"
    assert classify_failure(ValueError("bad")) == "defect"


def test_retry_transient_then_success(fake):
    err = json.dumps(ok_json(is_error=True, result="503 service unavailable"))
    fake.script({"stdout": err}, {"stdout": err}, {"stdout": json.dumps(ok_json())})
    sleeps = []
    runner = ClaudeRunner(claude_bin=fake.bin, env=fake.env)
    res = run_with_retry(runner, "hi", max_attempts=3, backoff=1.0, sleep=sleeps.append)
    assert res.ok and len(fake.calls()) == 3
    assert sleeps == [1.0, 2.0]


def test_retry_rate_limit_exhausts(fake):
    err = json.dumps(ok_json(is_error=True, result="rate limit"))
    fake.script({"stdout": err})
    runner = ClaudeRunner(claude_bin=fake.bin, env=fake.env)
    res = run_with_retry(runner, "hi", max_attempts=2, sleep=lambda s: None)
    assert not res.ok and res.error_kind == "rate_limit" and len(fake.calls()) == 2


def test_defect_never_retried(fake):
    fake.script({"stdout": json.dumps(ok_json(is_error=True, result="bad prompt"))})
    runner = ClaudeRunner(claude_bin=fake.bin, env=fake.env)
    res = run_with_retry(runner, "hi", max_attempts=3, sleep=lambda s: None)
    assert not res.ok and len(fake.calls()) == 1


def test_missing_binary_never_retried(tmp_path):
    runner = ClaudeRunner(claude_bin=str(tmp_path / "nope"))
    sleeps = []
    res = run_with_retry(runner, "hi", sleep=sleeps.append)
    assert res.error_kind == "runner_unavailable" and sleeps == []


def test_cost_guard_blocks_at_cap(fake):
    fake.script({"stdout": json.dumps(ok_json(total_cost_usd=1.0))})
    runner = ClaudeRunner(claude_bin=fake.bin, env=fake.env)
    guard = CostGuard(2.0)
    guard.run(runner, "a")
    guard.run(runner, "b")
    assert guard.spent_usd == 2.0 and guard.exhausted
    with pytest.raises(CostCapExceeded):
        guard.run(runner, "c")
    assert len(fake.calls()) == 2


def test_cost_guard_with_retry_and_disabled_cap(fake):
    fake.script({"stdout": json.dumps(ok_json(total_cost_usd=1.0))})
    runner = ClaudeRunner(claude_bin=fake.bin, env=fake.env)
    guard = CostGuard(1.0)
    run_with_retry(runner, "a", guard=guard)
    with pytest.raises(CostCapExceeded):
        run_with_retry(runner, "b", guard=guard)
    off = CostGuard(0)
    off.record(100.0)
    off.check()
