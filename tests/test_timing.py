import json

from conftest import ok_json

from claude_runner import RunResult, timing
from claude_runner.cli import main


def raw(api_ms, turns, ctx, out):
    return ok_json(
        duration_api_ms=api_ms,
        num_turns=turns,
        usage={"input_tokens": ctx, "output_tokens": out},
    )


def test_buckets_and_stats():
    runs = [raw(10_000, 2, 10_000, 1000), raw(20_000, 2, 100_000, 2000), {"num_turns": 1}]
    data = timing.stats(runs)
    assert data["runs"] == 2
    assert data["buckets"]["<20k"]["median_s_per_turn"] == 5.0
    assert data["buckets"]["<20k"]["median_s_per_1k_out"] == 10.0
    assert data["buckets"]["50-100k"]["runs"] == 1
    assert data["buckets"]["20-50k"]["runs"] == 0


def test_accepts_run_results():
    res = RunResult.from_json(raw(4000, 2, 40_000, 500))
    assert timing.stats([res])["buckets"]["20-50k"]["runs"] == 1


def test_report_text():
    text = timing.report([raw(10_000, 2, 10_000, 1000)])
    assert "med s/turn" in text and "<20k" in text and "not time to first token" in text
    assert timing.report([]) == "No runs with timing data."


def test_cli(tmp_path, capsys):
    p = tmp_path / "runs.jsonl"
    p.write_text(json.dumps(raw(10_000, 2, 10_000, 1000)) + "\nbroken\n\n")
    assert main([str(p)]) == 0
    assert "Runs: 1" in capsys.readouterr().out
    assert main([str(tmp_path / "missing.jsonl")]) == 2
