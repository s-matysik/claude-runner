"""Failure classification: decides whether another attempt can help."""

from __future__ import annotations

import re

from .result import RunResult, detect_rate_limit

TRANSIENT = "transient"
MISSING_INPUT = "missing_input"
DEFECT = "defect"
RATE_LIMIT = "rate_limit"

#: `RunResult.error_kind` values that are transient by nature.
TRANSIENT_KINDS = frozenset(
    {"timeout", "runner_exception", "killed", "network_error", "overloaded"}
)

#: `error_kind` values meaning something is missing that a retry cannot create.
MISSING_INPUT_KINDS = frozenset(
    {"runner_unavailable", "missing_input", "config_error", "auth", "precondition_failed"}
)

_TRANSIENT_TEXT_RE = re.compile(
    r"timed out|timeout|connection (?:reset|refused|aborted|error)"
    r"|temporar(?:y|ily) unavailable|service unavailable|bad gateway|gateway time-?out"
    r"|\b(?:http|status)[ :=]*5\d\d\b|\b5\d\d (?:server error|bad gateway|service unavailable)"
    r"|overloaded|econnreset|network is unreachable|name or service not known"
    r"|remote end closed|internal server error",
    re.IGNORECASE,
)


def _classify_text(kind: str, text: str) -> str:
    if kind == RATE_LIMIT or detect_rate_limit(text):
        return RATE_LIMIT
    if kind in TRANSIENT_KINDS:
        return TRANSIENT
    if kind in MISSING_INPUT_KINDS:
        return MISSING_INPUT
    if _TRANSIENT_TEXT_RE.search(text):
        return TRANSIENT
    return DEFECT


def classify_failure(result_or_exception: RunResult | BaseException) -> str:
    """Return "transient", "missing_input", "defect" or "rate_limit".

    Accepts a failed `RunResult` or an exception. Anything unrecognized is a
    "defect": rerunning the same prompt is not expected to change the outcome.
    """
    if isinstance(result_or_exception, BaseException):
        exc = result_or_exception
        if isinstance(exc, FileNotFoundError):
            return MISSING_INPUT
        text = f"{type(exc).__name__}: {exc}"
        kind = ""
        if isinstance(exc, (TimeoutError, ConnectionError)):
            kind = "network_error"
        return _classify_text(kind, text)
    result = result_or_exception
    return _classify_text((result.error_kind or "").strip(), result.error or "")


def is_retryable(failure_class: str) -> bool:
    """Only transient failures and rate limits are worth another attempt."""
    return failure_class in (TRANSIENT, RATE_LIMIT)
