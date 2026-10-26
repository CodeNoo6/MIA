import asyncio
from datetime import date, datetime, timezone

import mongomock
import pytest

from habits import charts, stats
from habits.store import NotFound, Store, make_goal

NOW = datetime(2026, 10, 25, 23, 30, tzinfo=timezone.utc)


@pytest.fixture
def store():
    return Store(mongomock.MongoClient(tz_aware=True)["habits"], "America/Bogota", now=lambda: NOW)


def test_trend_and_verdict_follow_repeat_thresholds():
    assert stats.trend(110, 100) == {"percentage": 10.0, "trend": "sube", "significant": False}
    assert stats.trend(80, 100)["significant"] is True
    assert stats.trend(103, 100)["trend"] == "estable"
    assert stats.trend(3, 0)["trend"] == "nuevo"
    assert stats.verdict("malo", "baja") == "mejora"
    assert stats.verdict("bueno", "baja") == "empeora"
    assert stats.verdict("neutral", "sube") is None


def test_periods_compare_to_the_same_point_of_the_previous_one():
    today = date(2026, 10, 25)
    assert stats.period_bounds("semana", today) == (date(2026, 10, 19), today)
    assert stats.previous_bounds("mes", today) == (date(2026, 9, 1), date(2026, 9, 25), date(2026, 9, 30))
    assert stats.previous_bounds("año", today)[1] == date(2025, 10, 25)


def test_streaks_count_runs_and_days_without():
    today = date(2026, 10, 25)
    entries = [stats.Entry(date(2026, 10, d), 1) for d in (10, 11, 12, 20, 24, 25)]
    result = stats.streaks(entries, today)
    assert result["current_days"] == 2 and result["longest_days"] == 3
    assert result["days_since_last"] == 0 and result["longest_gap_days"] == 7
    assert stats.streaks([stats.Entry(date(2026, 10, 13), 1)], today)["days_since_last"] == 12


def test_series_cover_the_whole_year_with_zeros():
    entries = [stats.Entry(date(2026, 1, 1), 2), stats.Entry(date(2026, 12, 31), 1), stats.Entry(date(2025, 6, 1), 9)]
    months = stats.series(entries, 2026, "mes")
    assert len(months) == 12 and months[0]["value"] == 2 and months[11]["value"] == 1
    assert len(stats.series(entries, 2026, "dia")) == 365
    weeks = stats.series(entries, 2026, "semana")
    assert weeks[0]["period"] == "2026-S01" and sum(w["value"] for w in weeks) == 3


def test_log_uses_the_users_day_and_matches_names_loosely(store):
    store.create_habit("ana", "Café", "tazas", "alimentacion", "neutral", aliases=["tinto"])
    logged = store.log("ana", "cafe", 2)
    assert logged["logged"]["day"] == "2026-10-25" and logged["logged"]["hour"] == 18
    store.log("ana", "TINTO", when="ayer")
    assert store.habits("ana")["habits"][0]["totals"]["dia"] == 2
    assert store.habits("ana")["habits"][0]["totals"]["semana"] == 3
    with pytest.raises(ValueError):
        store.log("ana", "cafe", when="2026-12-01")
    with pytest.raises(NotFound, match="Café"):
        store.log("ana", "Cafes")


def test_bad_habit_goal_streak_and_breakdown(store):
    goal = make_goal(5, "dia", None, "malo")
    assert goal == {"target": 5.0, "period": "dia", "direction": "max"}
    store.create_habit("ana", "Cigarrillos", "cigarrillos", "salud", "malo", goal=goal)
    store.log("ana", "cigarrillos", 4, when="2026-10-01", detail="después del almuerzo")
    store.log("ana", "cigarrillos", 6, when="2026-09-20")
    habit = store.log("ana", "cigarrillos", 6)["habit"]
    assert habit["goal_status"]["status"] == "superada"

    stats_ = store.habit_stats("ana", "cigarrillos")
    month = next(c for c in stats_["comparisons"] if c["period"] == "mes")
    assert month["value"] == 10 and month["previous_to_date"] == 6 and month["verdict"] == "empeora"
    assert stats_["top_details"][0]["detail"] == "después del almuerzo"
    assert stats_["by_weekday"]["domingo"] == 12 and stats_["by_weekday"]["jueves"] == 4


def test_users_are_isolated_and_undo_removes_the_last_entry(store):
    store.create_habit("ana", "Visitar a mamá", category="social", polarity="bueno")
    store.log("ana", "visitar a mama")
    store.log("ana", "visitar a mama", detail="almuerzo")
    assert store.habits("bruno")["habits"] == []
    with pytest.raises(NotFound):
        store.log("bruno", "visitar a mama")
    undone = store.delete_entry("ana")
    assert undone["detail"] == "almuerzo"
    assert store.habits("ana")["habits"][0]["totals"]["dia"] == 1
    with pytest.raises(ValueError):
        store.create_habit("ana", "visitar a MAMA")


def test_year_in_review_compares_with_last_year(store):
    store.create_habit("ana", "Cigarrillos", polarity="malo")
    store.create_habit("ana", "Gimnasio", polarity="bueno")
    store.log("ana", "cigarrillos", 100, when="2025-03-01")
    store.log("ana", "cigarrillos", 40, when="2026-03-01")
    store.log("ana", "gimnasio", 1, when="2026-03-02")
    summary = store.year_summary("ana", 2026)
    assert summary["improved"] == ["Cigarrillos"]
    cig = next(h for h in summary["habits"] if h["habit"] == "Cigarrillos")
    assert cig["vs_previous_year"]["percentage"] == -60.0 and cig["peak_month"] == "mar"
    assert charts.year_summary(summary)[:4] == b"\x89PNG"


def test_habit_chart_renders(store):
    store.create_habit("ana", "Cerveza", "cervezas", polarity="malo", goal=make_goal(8, "mes", None, "malo"))
    store.log("ana", "cerveza", 3, when="2026-02-14")
    daily = store.series("ana", "cerveza", 2026, "dia")
    monthly = store.series("ana", "cerveza", 2026, "mes")
    png = charts.habit_year("Cerveza", "cervezas", "malo", 2026, daily["series"], monthly["series"], monthly["goal"])
    assert png[:4] == b"\x89PNG"


def test_timezone_changes_what_today_means(store):
    assert store.today("ana").isoformat() == "2026-10-25"
    assert store.set_timezone("ana", "Europe/Madrid")["today"] == "2026-10-26"
    with pytest.raises(ValueError):
        store.set_timezone("ana", "Marte/Olympus")


def test_mcp_server_registers_every_tool():
    from mcp_server.server import mcp

    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert {"list_habits", "create_habit", "log", "habit_stats", "show_habit_chart", "year_in_review",
            "delete_entry", "habit_series"} <= names
