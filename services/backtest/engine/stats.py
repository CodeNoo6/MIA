"""Deterministic statistics for backtest audits.

Every function is pure: same inputs and seed, same output. The LLM layer never
calls into this module; it only reads results the engine already produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import comb, e, log, sqrt

import numpy as np
from scipy.stats import kurtosis, norm, skew

EULER_GAMMA = 0.5772156649015329
MAX_CSCV_SPLITS = 16


@dataclass(frozen=True)
class Moments:
    n: int
    mean: float
    std: float
    sharpe: float
    skew: float
    kurtosis: float


def moments(returns: np.ndarray) -> Moments:
    n = int(returns.size)
    if n < 3:
        raise ValueError("Se necesitan al menos 3 operaciones")
    std = float(np.std(returns, ddof=1))
    mean = float(np.mean(returns))
    sharpe = mean / std if std > 0 else 0.0
    return Moments(
        n=n,
        mean=mean,
        std=std,
        sharpe=sharpe,
        skew=float(skew(returns, bias=False)),
        kurtosis=float(kurtosis(returns, fisher=False, bias=False)),
    )


def sharpe_variance(m: Moments) -> float:
    """Variance of the Sharpe estimator under non-normal returns (Mertens/Opdyke)."""
    return (1 - m.skew * m.sharpe + (m.kurtosis - 1) / 4 * m.sharpe**2) / (m.n - 1)


def probabilistic_sharpe(m: Moments, benchmark: float = 0.0) -> float:
    denominator = sqrt(max(sharpe_variance(m) * (m.n - 1), 1e-12))
    return float(norm.cdf((m.sharpe - benchmark) * sqrt(m.n - 1) / denominator))


def expected_max_sharpe(trials: int, variance: float) -> float:
    """Expected maximum Sharpe among `trials` unskilled strategies (Bailey & López de Prado)."""
    if trials <= 1:
        return 0.0
    return sqrt(variance) * (
        (1 - EULER_GAMMA) * norm.ppf(1 - 1 / trials)
        + EULER_GAMMA * norm.ppf(1 - 1 / (trials * e))
    )


def deflated_sharpe(m: Moments, trials: int, trial_variance: float | None = None) -> dict:
    variance = trial_variance if trial_variance is not None else sharpe_variance(m)
    threshold = expected_max_sharpe(trials, variance)
    return {
        "trials": trials,
        "sharpe_threshold": threshold,
        "dsr": probabilistic_sharpe(m, threshold),
        "variance_source": "variantes" if trial_variance is not None else "estimador",
    }


def max_drawdown(pnl: np.ndarray) -> float:
    equity = np.cumsum(pnl)
    peaks = np.maximum.accumulate(np.concatenate(([0.0], equity)))[1:]
    return float(np.max(peaks - equity))


def monte_carlo_drawdown(
    pnl: np.ndarray, seed: int, sims: int, drawdown_limit: float | None
) -> dict:
    rng = np.random.default_rng(seed)
    samples = rng.choice(pnl, size=(sims, pnl.size), replace=True)
    equity = np.cumsum(samples, axis=1)
    peaks = np.maximum.accumulate(np.concatenate((np.zeros((sims, 1)), equity), axis=1), axis=1)
    drawdowns = np.max(peaks[:, 1:] - equity, axis=1)
    result = {
        "sims": sims,
        "histogram": histogram(drawdowns),
        "observed": max_drawdown(pnl),
        "p50": float(np.percentile(drawdowns, 50)),
        "p95": float(np.percentile(drawdowns, 95)),
        "p99": float(np.percentile(drawdowns, 99)),
    }
    if drawdown_limit is not None:
        result["drawdown_limit"] = drawdown_limit
        result["breach_probability"] = float(np.mean(drawdowns >= drawdown_limit))
    return result


def equity_curve(pnl: np.ndarray, max_points: int = 200) -> list[dict]:
    """Cumulative P&L and drawdown, evenly downsampled so a chart stays light."""
    equity = np.cumsum(pnl)
    drawdown = np.maximum.accumulate(np.concatenate(([0.0], equity)))[1:] - equity
    indexes = np.unique(np.linspace(0, pnl.size - 1, min(max_points, pnl.size)).astype(int))
    return [{"trade": int(i + 1), "equity": float(equity[i]), "drawdown": float(-drawdown[i])} for i in indexes]


def histogram(values: np.ndarray, bins: int = 20) -> list[dict]:
    counts, edges = np.histogram(values, bins=bins)
    return [
        {"from": float(edges[i]), "to": float(edges[i + 1]), "count": int(counts[i])}
        for i in range(counts.size)
    ]


def cost_sensitivity(pnl: np.ndarray, costs: np.ndarray, multipliers: list[float]) -> list[dict]:
    rows = []
    for multiplier in multipliers:
        net = pnl - costs * multiplier
        std = float(np.std(net, ddof=1))
        rows.append(
            {
                "multiplier": multiplier,
                "total": float(np.sum(net)),
                "sharpe": float(np.mean(net) / std) if std > 0 else 0.0,
            }
        )
    return rows


def segment_stats(pnl: np.ndarray) -> dict:
    std = float(np.std(pnl, ddof=1)) if pnl.size > 1 else 0.0
    return {
        "trades": int(pnl.size),
        "total": float(np.sum(pnl)),
        "sharpe": float(np.mean(pnl) / std) if std > 0 else 0.0,
        "win_rate": float(np.mean(pnl > 0)) if pnl.size else 0.0,
    }


def subperiods(pnl: np.ndarray, parts: int = 4) -> list[dict]:
    return [
        {"segment": index + 1, **segment_stats(chunk)}
        for index, chunk in enumerate(np.array_split(pnl, parts))
    ]


def volatility_regimes(pnl: np.ndarray, window: int = 20) -> list[dict]:
    """Split trades by terciles of trailing P&L volatility, a proxy until market data is wired in."""
    if pnl.size < window * 3:
        return []
    trailing = np.array(
        [np.std(pnl[max(0, i - window) : i], ddof=1) if i >= 2 else np.nan for i in range(pnl.size)]
    )
    valid = ~np.isnan(trailing)
    low, high = np.nanpercentile(trailing, [100 / 3, 200 / 3])
    labels = np.where(trailing <= low, "baja", np.where(trailing <= high, "media", "alta"))
    return [
        {"regime": label, **segment_stats(pnl[valid & (labels == label)])}
        for label in ("baja", "media", "alta")
    ]


def placebo_sign_test(pnl: np.ndarray, seed: int, sims: int) -> dict:
    """Compare the observed Sharpe with strategies whose trade direction is random."""
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(sims, pnl.size))
    randomized = signs * np.abs(pnl)
    std = np.std(randomized, axis=1, ddof=1)
    sharpes = np.divide(np.mean(randomized, axis=1), std, out=np.zeros(sims), where=std > 0)
    observed = moments(pnl).sharpe
    return {
        "sims": sims,
        "observed_sharpe": observed,
        "random_p95": float(np.percentile(sharpes, 95)),
        "p_value": float((np.sum(sharpes >= observed) + 1) / (sims + 1)),
    }


def _cscv_splits(rows: int) -> int:
    splits = min(MAX_CSCV_SPLITS, rows // 2)
    return splits - splits % 2


def probability_of_overfitting(matrix: np.ndarray) -> dict:
    """PBO by combinatorially symmetric cross-validation (Bailey et al., 2017).

    `matrix` holds one column per variant and one row per period, in time order.
    """
    rows, variants = matrix.shape
    splits = _cscv_splits(rows)
    if variants < 2 or splits < 4:
        raise ValueError("PBO requiere al menos 2 variantes y 8 periodos")
    blocks = np.array_split(np.arange(rows), splits)
    logits = []
    for in_sample in combinations(range(splits), splits // 2):
        out_sample = [b for b in range(splits) if b not in in_sample]
        is_rows = np.concatenate([blocks[b] for b in in_sample])
        oos_rows = np.concatenate([blocks[b] for b in out_sample])
        is_sharpe = _column_sharpe(matrix[is_rows])
        oos_sharpe = _column_sharpe(matrix[oos_rows])
        best = int(np.argmax(is_sharpe))
        rank = float(np.sum(oos_sharpe <= oos_sharpe[best]))
        omega = rank / (variants + 1)
        logits.append(log(omega / (1 - omega)))
    logits_array = np.array(logits)
    return {
        "variants": variants,
        "splits": splits,
        "combinations": comb(splits, splits // 2),
        "pbo": float(np.mean(logits_array <= 0)),
        "logit_median": float(np.median(logits_array)),
    }


def variant_sharpe_variance(matrix: np.ndarray) -> float:
    return float(np.var(_column_sharpe(matrix), ddof=1))


def _column_sharpe(matrix: np.ndarray) -> np.ndarray:
    std = np.std(matrix, axis=0, ddof=1)
    return np.divide(np.mean(matrix, axis=0), std, out=np.zeros(matrix.shape[1]), where=std > 0)
