# claude-runner

A small, dependency-free Python wrapper around `claude -p ... --output-format json` (the Claude Code CLI in print mode).

It gives you what you need to run Claude from scripts and job runners without writing the same glue every time:

- a typed `RunResult` (text, cost, session id, turns, durations, usage, permission denials);
- failure classification (`transient`, `rate_limit`, `missing_input`, `defect`) and a retry helper that retries only what a retry can fix;
- a per-job cost cap;
- an optional JSONL log of raw results and a timing report built from it.

Zero runtime dependencies, Python 3.10+, POSIX (macOS, Linux). It never talks to the network itself: it only runs the `claude` binary you already have installed and logged in.

## Install

```
pip install git+https://github.com/s-matysik/claude-runner
```

## Quick start

```python
from claude_runner import ClaudeRunner, CostGuard, run_with_retry

runner = ClaudeRunner(
    model="sonnet",
    max_turns=5,
    allowed_tools=["Read", "Grep"],
    cwd="/path/to/project",
    timeout_s=300,
    log_path="runs.jsonl",   # optional: one raw result per line (full model output, may be sensitive)
)

result = runner.run("Summarize the README in three bullets.")
if result.ok:
    print(result.output_text, result.cost_usd, result.num_turns)
else:
    print(result.error_kind, result.error)

# Retry transient failures and rate limits, never defects.
guard = CostGuard(cap_usd=3.0)
result = run_with_retry(runner, "Review src/", max_attempts=3, backoff=2.0, guard=guard)
```

`RunResult` fields: `ok`, `output_text`, `cost_usd`, `session_id`, `num_turns`, `duration_ms`, `duration_api_ms`, `usage`, `error`, `error_kind`, `permission_denials`, `raw`.

`run()` does not raise for CLI failures. `error_kind` is one of `timeout`, `rate_limit`, `runner_unavailable` (binary missing), `parse_error`, `claude_error`, or `None` on success.

## Retry policy

`classify_failure(result_or_exception)` returns one of four classes. `run_with_retry` acts on them:

| Class | Typical causes | Retried? |
|---|---|---|
| `transient` | timeout, HTTP 5xx, connection reset, overloaded, temporary unavailability | yes, with backoff |
| `rate_limit` | "rate limit", "usage limit", HTTP 429 | yes, with backoff |
| `missing_input` | `claude` binary not found, auth or config error | no |
| `defect` | anything else (model error, bad prompt, unparseable output) | no |

Backoff is exponential: `backoff=2.0` waits 2s, 4s, 8s, ... capped at 60s. Pass a callable `attempt -> seconds` for a custom schedule. Rate limits that reset in hours are not solved by short backoff; for those, catch `rate_limit` yourself and reschedule.

## Cost cap

```python
from claude_runner import CostGuard, CostCapExceeded

guard = CostGuard(cap_usd=3.0)          # one guard per job; 0 disables the cap
try:
    guard.run(runner, "step 1")
    guard.run(runner, "step 2")
except CostCapExceeded as exc:
    print(exc.spent_usd, exc.cap_usd)
```

The cap is checked before each run, so the run that crosses it still completes: the overshoot is at most one run. `run_with_retry(..., guard=guard)` checks and records every attempt. For a hard per-run limit, also pass `extra_args=["--max-budget-usd", "1.0"]`.

## Timing report

Enable `log_path=` on the runner, then:

```
claude-runner-report runs.jsonl
```

or from Python: `from claude_runner import timing; print(timing.report(results))` where `results` is a list of `RunResult` or raw JSON dicts.

```
Runs: 42, turns: 310

By average context per turn (API time, not time to first token):
  context     runs  med s/turn  p90 s/turn  med out/turn  med s/1k out
  <20k           6         4.2         9.8           310          13.1
  20-50k        18         6.0        14.5           420          14.0
  50-100k       11         8.7        19.2           450          19.3
  100-200k       5        12.4        25.0           520          23.8
  200-500k       2        21.0        30.1           610          34.5
  >500k          0           -           -             -             -
```

(Illustrative numbers.) Context per turn is `(input + cache read + cache creation tokens) / turns`. Note that `duration_api_ms` is the time the CLI spent in API calls, including generating the whole response. It is not time to first token, so do not read the table as a latency-to-first-token benchmark.

## Safety: permission modes

By default `ClaudeRunner` passes no `--permission-mode`, so the CLI's own default applies: in `-p` mode, tools that need approval are denied (they show up in `result.permission_denials`). Grant only what you need with `allowed_tools=[...]`.

`permission_mode="bypassPermissions"` is opt-in and dangerous: the model can run any tool, including shell commands and file writes, without asking. Use it only in a disposable sandbox or container, on a prompt you fully control, never on untrusted input.

The child process inherits your environment (the CLI needs it for authentication). Pass `env={...}` to restrict it.

## Limitations

- POSIX only (uses process groups to kill a timed-out run).
- Wraps the CLI's JSON output; field names depend on your installed `claude` version. Missing fields become `None` or empty.
- Classification is heuristic text matching on error messages. In particular, any error text containing "timeout" or "timed out" is treated as `transient`, even if the real cause is something a retry cannot fix.
- The prompt is passed as a command line argument (`claude -p <prompt>`), so it is visible to other local users via `ps` and is limited by the OS argument size limit (`ARG_MAX`). Do not put secrets in prompts, and keep very large inputs in files the model reads instead.
- The JSONL log (`log_path`) records the full raw response of every run, including the model's output text. It may contain sensitive data from your prompts, files or tool results; store it accordingly and do not commit it.
- Synchronous, one process per `run()`; no streaming output.
- The cost cap is checked between runs, not during one.

## Development

```
pip install -e '.[dev]'
pytest
ruff check .
```

Tests use a fake `claude` executable; they never call the real CLI or the network.

## License

MIT, see [LICENSE](LICENSE).
