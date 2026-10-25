"""Render the audit chart as a PNG from a stored record. Plots only values the engine computed."""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

NAVY = "#132033"
RED = "#C0392B"
GRAY = "#8A94A6"


def render_png(record: dict) -> bytes:
    """Equity curve with the drawdown shaded between the running peak and the equity."""
    curve = record["charts"]["equity_curve"]
    trades = [p["trade"] for p in curve]
    equity = [p["equity"] for p in curve]
    peaks = [e - p["drawdown"] for e, p in zip(equity, curve)]

    figure, axis = plt.subplots(figsize=(9, 4.5))
    axis.plot(trades, equity, color=NAVY, linewidth=2, label="Capital acumulado")
    axis.fill_between(trades, equity, peaks, color=RED, alpha=0.2, label="Drawdown")
    axis.axhline(0, color=GRAY, linewidth=0.8)
    axis.set_title("Curva de capital y drawdown", loc="left", fontsize=13, color=NAVY)
    axis.set_xlabel("Operación")
    axis.legend(loc="best", frameon=False)
    axis.spines[["top", "right"]].set_visible(False)
    figure.text(
        0.99,
        0.01,
        f"Informe {record['run_id'][:12]} · N = {record['combinations_examined']}",
        ha="right",
        fontsize=8,
        color=GRAY,
    )
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=120)
    plt.close(figure)
    return buffer.getvalue()
