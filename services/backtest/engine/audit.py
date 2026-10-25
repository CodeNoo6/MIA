"""Ingest a trades file and assemble the full, reproducible audit result (FR-01 to FR-08, FR-21)."""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass

import numpy as np

from engine import stats

ENGINE_VERSION = "0.1.0"
PNL_COLUMNS = ("pnl", "profit", "p&l", "net_profit", "beneficio")
FEE_COLUMNS = ("fees", "fee", "commission", "comision", "comisión")
TIME_COLUMNS = ("timestamp", "time", "date", "close_time", "fecha")


@dataclass(frozen=True)
class AuditParams:
    declared_variants: int = 1
    cost_multiplier: float = 1.0
    cost_per_trade: float = 0.0
    drawdown_limit: float | None = None
    seed: int = 42
    sims: int = 5000


@dataclass(frozen=True)
class Trades:
    pnl: np.ndarray
    fees: np.ndarray
    timestamps: list[str]


def _find(header: list[str], candidates: tuple[str, ...]) -> int | None:
    lowered = [h.strip().lower() for h in header]
    return next((lowered.index(c) for c in candidates if c in lowered), None)


def _number(value: str) -> float:
    return float(value.strip().replace(",", "") or 0)


def parse_trades(raw: bytes) -> Trades:
    """Accept a CSV export with a P&L column and optional fee and time columns."""
    text = raw.decode("utf-8-sig")
    dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    rows = list(csv.reader(io.StringIO(text), dialect))
    header, body = rows[0], [r for r in rows[1:] if any(cell.strip() for cell in r)]
    pnl_index = _find(header, PNL_COLUMNS)
    if pnl_index is None:
        raise ValueError(f"No se encontró una columna de P&L. Usa una de: {', '.join(PNL_COLUMNS)}")
    fee_index = _find(header, FEE_COLUMNS)
    time_index = _find(header, TIME_COLUMNS)
    return Trades(
        pnl=np.array([_number(r[pnl_index]) for r in body]),
        fees=np.array([_number(r[fee_index]) for r in body]) if fee_index is not None else np.zeros(len(body)),
        timestamps=[r[time_index] for r in body] if time_index is not None else [],
    )


def parse_variants(raw: bytes) -> np.ndarray:
    """One column per variant, one row per period, numeric returns only."""
    text = raw.decode("utf-8-sig")
    rows = [r for r in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in r)]
    return np.array([[_number(cell) for cell in r] for r in rows[1:]])


def run_audit(
    trades: Trades, params: AuditParams, combinations_examined: int, variants: np.ndarray | None
) -> dict:
    """`combinations_examined` is the N used for deflation: declared variants plus every rerun."""
    costs = trades.fees + params.cost_per_trade
    net = trades.pnl - costs * params.cost_multiplier
    m = stats.moments(net)
    variance = stats.variant_sharpe_variance(variants) if variants is not None else None
    result: dict = {
        "engine_version": ENGINE_VERSION,
        "params": asdict(params),
        "combinations_examined": combinations_examined,
        "trades": m.n,
        "period": {"start": trades.timestamps[0], "end": trades.timestamps[-1]} if trades.timestamps else None,
        "summary": {
            "total": float(np.sum(net)),
            "mean": m.mean,
            "std": m.std,
            "sharpe_per_trade": m.sharpe,
            "skew": m.skew,
            "kurtosis": m.kurtosis,
            "win_rate": float(np.mean(net > 0)),
            "max_drawdown": stats.max_drawdown(net),
        },
        "psr": stats.probabilistic_sharpe(m),
        "deflated_sharpe": stats.deflated_sharpe(m, combinations_examined, variance),
        "monte_carlo": stats.monte_carlo_drawdown(net, params.seed, params.sims, params.drawdown_limit),
        "cost_sensitivity": stats.cost_sensitivity(trades.pnl, costs, [0.0, 1.0, 2.0, 3.0]),
        "subperiods": stats.subperiods(net),
        "volatility_regimes": stats.volatility_regimes(net),
        "placebo": stats.placebo_sign_test(net, params.seed, params.sims),
        "pbo": None,
        "market_context": None,
        "charts": {"equity_curve": stats.equity_curve(net)},
    }
    if variants is not None:
        result["pbo"] = stats.probability_of_overfitting(variants)
    return result
