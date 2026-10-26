"""Pure statistics over habit entries, ported from the Repeat iOS app: period totals with their comparison
against the previous period, goals, streaks, distributions and chart series.

Entries reach these functions as (day, value, detail, hour) tuples where `day` is the user's local ISO date.
"""

from __future__ import annotations

import calendar
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from typing import NamedTuple

PERIODS = ("dia", "semana", "mes", "año")
GRANULARITIES = ("dia", "semana", "mes")
POLARITIES = ("bueno", "malo", "neutral")
WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
TREND_THRESHOLD = 5
SIGNIFICANT_THRESHOLD = 10


class Entry(NamedTuple):
    day: date
    value: float
    detail: str | None = None
    hour: int | None = None


def normalize(text: str) -> str:
    """Lowercase without accents or extra spaces, for matching 'Café' with 'cafe'."""
    stripped = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return " ".join(stripped.lower().split())


def period_bounds(period: str, today: date) -> tuple[date, date]:
    """First day of the current period and today. Weeks start on Monday."""
    if period == "dia":
        return today, today
    if period == "semana":
        return today - timedelta(days=today.weekday()), today
    if period == "mes":
        return today.replace(day=1), today
    if period == "año":
        return today.replace(month=1, day=1), today
    raise ValueError(f"Periodo desconocido. Opciones: {', '.join(PERIODS)}")


def previous_bounds(period: str, today: date) -> tuple[date, date, date]:
    """Start of the previous period, the same elapsed point in it, and its last day."""
    start, _ = period_bounds(period, today)
    elapsed = (today - start).days
    if period == "dia":
        prev_start = today - timedelta(days=1)
        return prev_start, prev_start, prev_start
    if period == "semana":
        prev_start = start - timedelta(days=7)
        return prev_start, prev_start + timedelta(days=elapsed), start - timedelta(days=1)
    if period == "mes":
        prev_end = start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        return prev_start, min(prev_start + timedelta(days=elapsed), prev_end), prev_end
    prev_start = start.replace(year=start.year - 1)
    prev_end = start - timedelta(days=1)
    same = today.replace(year=today.year - 1, day=min(today.day, calendar.monthrange(today.year - 1,
                                                                                     today.month)[1]))
    return prev_start, same, prev_end


def total(entries: Iterable[Entry], start: date, end: date) -> float:
    return sum(e.value for e in entries if start <= e.day <= end)


def trend(current: float, previous: float) -> dict:
    """Change against the previous period with Repeat's thresholds: ±5% is a trend, beyond 10% is significant."""
    if previous == 0:
        return {"percentage": None, "trend": "nuevo" if current else "estable", "significant": False}
    percentage = (current - previous) / previous * 100
    direction = "sube" if percentage > TREND_THRESHOLD else "baja" if percentage < -TREND_THRESHOLD else "estable"
    return {"percentage": round(percentage, 1), "trend": direction,
            "significant": abs(percentage) > SIGNIFICANT_THRESHOLD}


def verdict(polarity: str, direction: str) -> str | None:
    """Whether a trend is good news: fewer cigarettes is an improvement, fewer workouts is not."""
    if polarity == "neutral" or direction in ("estable", "nuevo"):
        return None
    improving = (direction == "baja") == (polarity == "malo")
    return "mejora" if improving else "empeora"


def compare(entries: list[Entry], period: str, today: date, polarity: str) -> dict:
    start, end = period_bounds(period, today)
    prev_start, prev_same, prev_end = previous_bounds(period, today)
    current = total(entries, start, end)
    previous_to_date = total(entries, prev_start, prev_same)
    change = trend(current, previous_to_date)
    return {
        "period": period, "from": start.isoformat(), "to": end.isoformat(), "value": current,
        "previous_to_date": previous_to_date, "previous_full": total(entries, prev_start, prev_end),
        **change, "verdict": verdict(polarity, change["trend"]),
    }


def goal_status(entries: list[Entry], goal: dict | None, today: date) -> dict | None:
    """Progress of the current period against a 'max' (limit) or 'min' (target) goal."""
    if not goal:
        return None
    start, end = period_bounds(goal["period"], today)
    value = total(entries, start, end)
    target = goal["target"]
    if goal["direction"] == "max":
        status = "superada" if value > target else "en el límite" if value == target else "dentro"
        remaining = max(0.0, target - value)
    else:
        status = "cumplida" if value >= target else "pendiente"
        remaining = max(0.0, target - value)
    return {**goal, "value": value, "status": status, "remaining": remaining}


def streaks(entries: list[Entry], today: date) -> dict:
    """Current and longest run of consecutive days with an entry, and days since the last one (for bad
    habits this is the run without it)."""
    days = sorted({e.day for e in entries if e.day <= today})
    if not days:
        return {"current_days": 0, "longest_days": 0, "days_since_last": None, "longest_gap_days": None,
                "last": None}
    longest = run = 1
    longest_gap = 0
    for previous, current in zip(days, days[1:]):
        gap = (current - previous).days
        run = run + 1 if gap == 1 else 1
        longest = max(longest, run)
        longest_gap = max(longest_gap, gap - 1)
    since = (today - days[-1]).days
    current = run if since <= 1 else 0
    return {"current_days": current, "longest_days": longest, "days_since_last": since,
            "longest_gap_days": max(longest_gap, since), "last": days[-1].isoformat()}


def distributions(entries: list[Entry]) -> dict:
    by_weekday = Counter()
    by_hour = Counter()
    by_detail = Counter()
    for entry in entries:
        by_weekday[WEEKDAYS[entry.day.weekday()]] += entry.value
        if entry.hour is not None:
            by_hour[entry.hour] += entry.value
        if entry.detail:
            by_detail[entry.detail] += entry.value
    return {
        "by_weekday": {day: by_weekday.get(day, 0) for day in WEEKDAYS},
        "top_hours": [{"hour": h, "value": v} for h, v in by_hour.most_common(3)],
        "top_details": [{"detail": d, "value": v} for d, v in by_detail.most_common(10)],
    }


def series(entries: list[Entry], year: int, granularity: str) -> list[dict]:
    """Totals for every day, ISO week or month of a year, zeros included, ready to chart."""
    if granularity not in GRANULARITIES:
        raise ValueError(f"Granularidad desconocida. Opciones: {', '.join(GRANULARITIES)}")
    sums: dict[str, float] = defaultdict(float)
    for entry in entries:
        if entry.day.year != year:
            continue
        sums[_bucket(entry.day, granularity)] += entry.value
    return [{"period": key, "value": sums.get(key, 0)} for key in _buckets(year, granularity)]


def _bucket(day: date, granularity: str) -> str:
    if granularity == "dia":
        return day.isoformat()
    if granularity == "semana":
        first_monday = date(day.year, 1, 1).toordinal() - date(day.year, 1, 1).weekday()
        return f"{day.year}-S{(day.toordinal() - first_monday) // 7 + 1:02d}"
    return f"{day.year}-{day.month:02d}"


def _buckets(year: int, granularity: str) -> list[str]:
    first = date(year, 1, 1)
    days = [first + timedelta(days=i) for i in range((date(year + 1, 1, 1) - first).days)]
    return list(dict.fromkeys(_bucket(day, granularity) for day in days))


def year_summary(entries: list[Entry], year: int) -> dict:
    this_year = [e for e in entries if e.day.year == year]
    months = series(this_year, year, "mes")
    peak = max(months, key=lambda m: m["value"]) if any(m["value"] for m in months) else None
    active_days = len({e.day for e in this_year})
    return {
        "year": year, "total": sum(e.value for e in this_year), "active_days": active_days,
        "previous_year_total": sum(e.value for e in entries if e.day.year == year - 1),
        "peak_month": MONTHS[int(peak["period"][-2:]) - 1] if peak else None,
        "monthly": [{"month": MONTHS[i], "value": m["value"]} for i, m in enumerate(months)],
        **{key: value for key, value in distributions(this_year).items() if key != "top_hours"},
    }
