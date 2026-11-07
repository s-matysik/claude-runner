"""The normalized result of one `claude -p` run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Substrings (checked case-insensitively) that mark a failure as a rate or
#: usage limit rather than a genuine model failure.
RATE_LIMIT_MARKERS = ("rate limit", "usage limit", "overloaded", "429")


def detect_rate_limit(text: str | None) -> bool:
    """True if `text` looks like a rate/usage limit message."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in RATE_LIMIT_MARKERS)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


@dataclass
class RunResult:
    """Outcome of one run. `ok` is False for any failure; see `error_kind`."""

    ok: bool
    output_text: str = ""
    cost_usd: float = 0.0
    session_id: str | None = None
    num_turns: int | None = None
    duration_ms: float | None = None
    duration_api_ms: float | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    #: "timeout", "rate_limit", "runner_unavailable", "parse_error", "claude_error" or None.
    error_kind: str | None = None
    permission_denials: list[Any] = field(default_factory=list)
    #: The parsed JSON object from the CLI, or {"stdout", "stderr", "returncode"} on failure.
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RunResult:
        """Build a result from the CLI's `--output-format json` object."""
        is_error = bool(data.get("is_error"))
        text = str(data.get("result") or "")
        turns = _num(data.get("num_turns"))
        usage = data.get("usage")
        denials = data.get("permission_denials")
        return cls(
            ok=not is_error,
            output_text=text,
            cost_usd=_num(data.get("total_cost_usd")) or 0.0,
            session_id=data.get("session_id"),
            num_turns=int(turns) if turns is not None else None,
            duration_ms=_num(data.get("duration_ms")),
            duration_api_ms=_num(data.get("duration_api_ms")),
            usage=usage if isinstance(usage, dict) else {},
            error=text if is_error else None,
            error_kind=None,
            permission_denials=denials if isinstance(denials, list) else [],
            raw=data,
        )
