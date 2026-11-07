"""Timing report: seconds per turn by average context size.

`duration_api_ms` is the time the CLI spent in API calls. It is NOT time to
first token: it covers whole responses, including generation.
"""

from __future__ import annotations

from collections.abc import Iterable
from statistics import median
from typing import Any

from .result import RunResult

#: (label, lower bound inclusive, upper bound exclusive) of average context per turn.
CONTEXT_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("<20k", 0, 20_000),
    ("20-50k", 20_000, 50_000),
    ("50-100k", 50_000, 100_000),
    ("100-200k", 100_000, 200_000),
    ("200-500k", 200_000, 500_000),
    (">500k", 500_000, float("inf")),
)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_run(item: RunResult | dict[str, Any]) -> dict[str, float | None] | None:
    """Timing metrics of one run, or None when duration or turns are missing."""
    if isinstance(item, RunResult):
        api_ms, turns, usage = item.duration_api_ms, item.num_turns, item.usage
    elif isinstance(item, dict):
        api_ms = _num(item.get("duration_api_ms"))
        turns = _num(item.get("num_turns"))
        usage = item.get("usage")
    else:
        return None
    if not api_ms or not turns or api_ms <= 0 or turns <= 0:
        return None
    usage = usage if isinstance(usage, dict) else {}
    context = sum(
        _num(usage.get(k)) or 0.0
        for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )
    out_tokens = _num(usage.get("output_tokens")) or 0.0
    api_s = api_ms / 1000
    return {
        "turns": float(turns),
        "s_per_turn": api_s / turns,
        "ctx_per_turn": context / turns,
        "out_per_turn": out_tokens / turns,
        "s_per_1k_out": api_s / (out_tokens / 1000) if out_tokens > 0 else None,
    }


def _p90(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(0.9 * len(s)))]


def _bucket_of(ctx: float) -> str:
    for label, lo, hi in CONTEXT_BUCKETS:
        if lo <= ctx < hi:
            return label
    return CONTEXT_BUCKETS[-1][0]


def _stats(runs: list[dict[str, float | None]]) -> dict[str, Any]:
    s_turn = [r["s_per_turn"] for r in runs]
    per_1k = [r["s_per_1k_out"] for r in runs if r["s_per_1k_out"] is not None]
    return {
        "runs": len(runs),
        "median_s_per_turn": median(s_turn) if s_turn else None,
        "p90_s_per_turn": _p90(s_turn),
        "median_out_per_turn": median([r["out_per_turn"] for r in runs]) if runs else None,
        "median_s_per_1k_out": median(per_1k) if per_1k else None,
    }


def stats(results: Iterable[RunResult | dict[str, Any]]) -> dict[str, Any]:
    """Aggregate runs into context buckets. Runs without timing data are skipped."""
    runs = [r for r in (parse_run(x) for x in results) if r]
    return {
        "runs": len(runs),
        "turns": int(sum(r["turns"] or 0 for r in runs)),
        "max_ctx": max((r["ctx_per_turn"] or 0.0 for r in runs), default=0.0),
        "buckets": {
            label: _stats([r for r in runs if _bucket_of(r["ctx_per_turn"] or 0.0) == label])
            for label, _, _ in CONTEXT_BUCKETS
        },
    }


def _f(value: float | None, fmt: str = "{:.1f}") -> str:
    return "-" if value is None else fmt.format(value)


def report(results: Iterable[RunResult | dict[str, Any]]) -> str:
    """Plain-text context-bucket table from RunResults or raw JSON dicts."""
    data = stats(results)
    if not data["runs"]:
        return "No runs with timing data."
    lines = [
        f"Runs: {data['runs']}, turns: {data['turns']}",
        "",
        "By average context per turn (API time, not time to first token):",
        f"  {'context':<10}{'runs':>6}{'med s/turn':>12}{'p90 s/turn':>12}"
        f"{'med out/turn':>14}{'med s/1k out':>14}",
    ]
    for label, s in data["buckets"].items():
        lines.append(
            f"  {label:<10}{s['runs']:>6}{_f(s['median_s_per_turn']):>12}"
            f"{_f(s['p90_s_per_turn']):>12}{_f(s['median_out_per_turn'], '{:.0f}'):>14}"
            f"{_f(s['median_s_per_1k_out']):>14}"
        )
    lines += ["", f"Largest average context of a single run: {data['max_ctx']:,.0f} tokens"]
    return "\n".join(lines)
