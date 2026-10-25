import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from engine import stats
from engine.audit import AuditParams, parse_trades, run_audit

SAMPLE = Path(__file__).resolve().parent.parent / "sample"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from engine import api
    from engine.store import RunStore

    monkeypatch.setattr(api, "store", RunStore(tmp_path))
    return TestClient(api.app)


def upload(client, declared_variants=1, with_variants=False):
    files = {"trades": ("trades.csv", (SAMPLE / "trades.csv").read_bytes(), "text/csv")}
    if with_variants:
        files["variants"] = ("variants.csv", (SAMPLE / "variants.csv").read_bytes(), "text/csv")
    response = client.post("/runs", files=files, data={"declared_variants": str(declared_variants)})
    assert response.status_code == 200, response.text
    return response.json()


def test_deflated_sharpe_falls_as_more_combinations_are_examined():
    returns = np.random.default_rng(1).normal(0.1, 1, 400)
    m = stats.moments(returns)
    values = [stats.deflated_sharpe(m, n)["dsr"] for n in (1, 10, 100, 1000)]
    assert values == sorted(values, reverse=True)
    assert stats.deflated_sharpe(m, 1)["dsr"] == pytest.approx(stats.probabilistic_sharpe(m))


def test_pbo_separates_noise_from_a_dominant_variant():
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 1, (240, 10))
    assert stats.probability_of_overfitting(noise)["pbo"] > 0.2
    dominant = noise.copy()
    dominant[:, 0] += 1.0
    assert stats.probability_of_overfitting(dominant)["pbo"] < 0.05


def test_audit_is_deterministic_for_a_fixed_seed():
    trades = parse_trades((SAMPLE / "trades.csv").read_bytes())
    first = run_audit(trades, AuditParams(seed=9), 1, None)
    second = run_audit(trades, AuditParams(seed=9), 1, None)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["monte_carlo"]["p95"] >= first["monte_carlo"]["p50"]


def test_parse_trades_rejects_files_without_pnl():
    with pytest.raises(ValueError, match="P&L"):
        parse_trades(b"date,price\n2026-01-01,10\n")


def test_rerun_raises_the_family_combination_count(client):
    original = upload(client, declared_variants=5)
    assert original["combinations_examined"] == 5
    doubled = client.post(f"/runs/{original['run_id']}/rerun", json={"cost_multiplier": 2}).json()
    assert doubled["combinations_examined"] == 6
    assert doubled["family_id"] == original["family_id"]
    assert doubled["summary"]["total"] < original["summary"]["total"]
    again = client.post(f"/runs/{doubled['run_id']}/rerun", json={"cost_multiplier": 3}).json()
    assert again["combinations_examined"] == 7
    assert again["deflated_sharpe"]["dsr"] < original["deflated_sharpe"]["dsr"]


def test_variants_enable_pbo(client):
    record = upload(client, declared_variants=12, with_variants=True)
    assert record["pbo"]["variants"] == 12
    assert record["deflated_sharpe"]["variance_source"] == "variantes"


def test_report_hash_detects_tampering(client, tmp_path):
    record = upload(client)
    assert client.get(f"/runs/{record['run_id']}/verify").json()["valid"] is True
    path = tmp_path / "runs" / record["run_id"] / "result.json"
    stored = json.loads(path.read_text())
    stored["summary"]["total"] += 1000
    path.write_text(json.dumps(stored))
    assert client.get(f"/runs/{record['run_id']}/verify").json()["valid"] is False


def test_pdf_and_missing_runs(client):
    record = upload(client)
    pdf = client.get(f"/runs/{record['run_id']}/report.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    png = client.get(f"/runs/{record['run_id']}/charts.png")
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    assert client.get("/runs/doesnotexist").status_code == 404
    assert client.get("/runs/..%2F..%2Fetc").status_code == 404


def test_chart_series_match_the_audited_trades():
    trades = parse_trades((SAMPLE / "trades.csv").read_bytes())
    result = run_audit(trades, AuditParams(), 1, None)
    curve = result["charts"]["equity_curve"]
    assert len(curve) <= 200 and curve[-1]["trade"] == trades.pnl.size
    assert curve[-1]["equity"] == pytest.approx(result["summary"]["total"])
    assert min(point["drawdown"] for point in curve) >= -result["summary"]["max_drawdown"] - 1e-9
    assert sum(b["count"] for b in result["monte_carlo"]["histogram"]) == result["monte_carlo"]["sims"]
