"""claude-runner: a small wrapper around `claude -p --output-format json`."""

from . import timing
from .cost import CostCapExceeded, CostGuard
from .failures import (
    DEFECT,
    MISSING_INPUT,
    RATE_LIMIT,
    TRANSIENT,
    classify_failure,
    is_retryable,
)
from .result import RunResult, detect_rate_limit
from .retry import exponential_backoff, run_with_retry
from .runner import ClaudeRunner

__version__ = "0.1.0"

__all__ = [
    "DEFECT",
    "MISSING_INPUT",
    "RATE_LIMIT",
    "TRANSIENT",
    "ClaudeRunner",
    "CostCapExceeded",
    "CostGuard",
    "RunResult",
    "classify_failure",
    "detect_rate_limit",
    "exponential_backoff",
    "is_retryable",
    "run_with_retry",
    "timing",
]
