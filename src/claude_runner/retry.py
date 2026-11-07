"""Retry policy: only transient failures and rate limits, with backoff."""

from __future__ import annotations

import time
from collections.abc import Callable

from .cost import CostGuard
from .failures import classify_failure, is_retryable
from .result import RunResult


def exponential_backoff(base_s: float = 2.0, factor: float = 2.0, max_s: float = 60.0):
    """Return a function mapping the failed attempt number (1-based) to a delay."""

    def delay(attempt: int) -> float:
        return min(max_s, base_s * factor ** (attempt - 1))

    return delay


def run_with_retry(
    runner,
    prompt: str,
    max_attempts: int = 3,
    backoff: float | Callable[[int], float] | None = None,
    guard: CostGuard | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> RunResult:
    """Run `prompt`, retrying only "transient" and "rate_limit" failures.

    `backoff` is a base delay in seconds (doubled per attempt, capped at 60s),
    or a callable `attempt -> seconds`. Defaults to a 2s base. A "defect" or
    "missing_input" failure is returned at once, never retried. With a
    `guard`, every attempt is cost-checked first (may raise `CostCapExceeded`)
    and recorded. Returns the last result; if the runner itself raises a
    non-retryable exception it propagates.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if backoff is None:
        delay_fn = exponential_backoff()
    elif callable(backoff):
        delay_fn = backoff
    else:
        delay_fn = exponential_backoff(float(backoff))

    result: RunResult | None = None
    for attempt in range(1, max_attempts + 1):
        if guard is not None:
            guard.check()
        try:
            result = runner.run(prompt)
        except Exception as exc:
            if attempt >= max_attempts or not is_retryable(classify_failure(exc)):
                raise
            sleep(delay_fn(attempt))
            continue
        if guard is not None:
            guard.record(result)
        if result.ok or not is_retryable(classify_failure(result)):
            return result
        if attempt < max_attempts:
            sleep(delay_fn(attempt))
    assert result is not None
    return result
