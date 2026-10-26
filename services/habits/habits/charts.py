"""PNG charts drawn from series the store already computed: a habit's year (calendar heatmap plus monthly
bars) and the year-end summary of every habit. Nothing here computes statistics."""

from __future__ import annotations

import io
from datetime import date

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from habits import stats  # noqa: E402

PALETTE = {"bueno": "#2E9E5B", "malo": "#D64545", "neutral": "#7C4DFF"}
INK, MUTED, GRID, EMPTY = "#221E2E", "#6E6880", "#E6E0F5", "#EEEAF6"


def _png(fig: plt.Figure) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buffer.getvalue()


def _style(ax: plt.Axes) -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def habit_year(name: str, unit: str, polarity: str, year: int, daily: list[dict], monthly: list[dict],
               goal: dict | None = None) -> bytes:
    """Calendar heatmap of every day of the year on top, monthly totals below."""
    color = PALETTE.get(polarity, PALETTE["neutral"])
    cmap = LinearSegmentedColormap.from_list("habit", [EMPTY, color])
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(11, 5), gridspec_kw={"height_ratios": [0.75, 1]})
    fig.suptitle(f"{name} · {year}", x=0.02, y=0.98, ha="left", fontsize=16, fontweight="bold", color=INK)
    fig.subplots_adjust(top=0.9, hspace=0.35)

    first = date(year, 1, 1)
    offset = first.weekday()
    weeks = (offset + len(daily) + 6) // 7
    grid = [[float("nan")] * weeks for _ in range(7)]
    for index, point in enumerate(daily):
        slot = offset + index
        grid[slot % 7][slot // 7] = point["value"]
    peak = max((p["value"] for p in daily), default=0) or 1
    top.imshow([[0 if v != v else v for v in row] for row in grid], cmap=cmap, vmin=0, vmax=peak, aspect="equal")
    for row in range(7):
        for col in range(weeks):
            if grid[row][col] != grid[row][col]:
                top.add_patch(plt.Rectangle((col - 0.5, row - 0.5), 1, 1, color="white"))
    top.set_yticks(range(7), ["L", "M", "X", "J", "V", "S", "D"])
    month_starts = [((offset + (date(year, m, 1) - first).days) // 7, stats.MONTHS[m - 1]) for m in range(1, 13)]
    top.set_xticks([c for c, _ in month_starts], [label for _, label in month_starts])
    top.tick_params(length=0, colors=MUTED, labelsize=9)
    for spine in top.spines.values():
        spine.set_visible(False)
    top.set_title(f"Cada cuadro es un día; más intenso = más {unit}", loc="left", fontsize=10, color=MUTED)

    values = [m["value"] for m in monthly]
    bottom.bar(stats.MONTHS, values, color=color, width=0.65)
    if goal and goal.get("period") == "mes":
        bottom.axhline(goal["target"], color=INK, linestyle="--", linewidth=1)
        bottom.text(11.4, goal["target"], f" meta {goal['target']:g}", va="bottom", ha="right", fontsize=9,
                    color=INK)
    for index, value in enumerate(values):
        if value:
            bottom.text(index, value, f"{value:g}", ha="center", va="bottom", fontsize=9, color=INK)
    bottom.set_ylabel(unit, color=MUTED)
    _style(bottom)
    fig.text(0.02, -0.02, f"Total {year}: {sum(values):g} {unit} · MIA · Agente de Hábitos", fontsize=9,
             color=MUTED)
    return _png(fig)


def year_summary(summary: dict) -> bytes:
    """One horizontal bar per habit with this year's total and the change against last year."""
    items = summary["habits"]
    fig, ax = plt.subplots(figsize=(10, 1.6 + 0.55 * max(1, len(items))))
    fig.suptitle(f"Tu año {summary['year']} en hábitos", x=0.02, ha="left", fontsize=16, fontweight="bold",
                 color=INK)
    if not items:
        ax.text(0.5, 0.5, "Aún no hay registros este año.", ha="center", va="center", color=MUTED)
        ax.axis("off")
        return _png(fig)
    names = [f"{i['habit']} ({i['unit']})" for i in items]
    totals = [i["total"] for i in items]
    ax.barh(names, totals, color=[PALETTE.get(i["polarity"], PALETTE["neutral"]) for i in items], height=0.55)
    ax.set_ylim(len(items) - 0.4, -0.6)
    peak = max(totals) or 1
    for row, item in enumerate(items):
        change = item["vs_previous_year"]
        note = "" if change["percentage"] is None else f"  {change['percentage']:+.0f}% vs {summary['year'] - 1}"
        mark = {"mejora": " ✓", "empeora": " ✗"}.get(item.get("verdict") or "", "")
        ax.text(item["total"] + peak * 0.01, row, f"{item['total']:g}{note}{mark}", va="center", fontsize=9,
                color=INK)
    ax.set_xlim(0, peak * 1.35)
    _style(ax)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", colors=INK, labelsize=10)
    fig.text(0.02, -0.02, "Verde: hábitos buenos · Rojo: hábitos a reducir · Morado: neutros · MIA", fontsize=9,
             color=MUTED)
    return _png(fig)

