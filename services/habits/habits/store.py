"""Owner-scoped persistence for the habits agent on MongoDB.

Every read and write is filtered by `owner`, the MIA user id the MCP receives from LibreChat. Days are stored
in the user's own time zone so "today" and "yesterday" mean what the user means.
"""

from __future__ import annotations

import difflib
import time
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

from habits import stats

CATEGORIES = ("salud", "alimentacion", "social", "productividad", "estilo_de_vida", "fitness", "finanzas", "otro")
GOAL_PERIODS = ("dia", "semana", "mes")
RELATIVE_DAYS = {"hoy": 0, "ayer": 1, "anteayer": 2, "antier": 2}
HABIT_FIELDS = ("name", "unit", "category", "polarity", "aliases", "goal", "notes")


class NotFound(ValueError):
    pass


def _id() -> str:
    return uuid.uuid4().hex[:12]


def _public(doc: dict) -> dict:
    out = {key: value for key, value in doc.items() if key not in ("_id", "owner", "key", "keys")}
    out["id"] = doc["_id"]
    return out


def _entry(doc: dict) -> stats.Entry:
    return stats.Entry(date.fromisoformat(doc["day"]), doc["value"], doc.get("detail"), doc.get("hour"))


def make_goal(target: float | None, period: str | None, direction: str | None, polarity: str) -> dict | None:
    """A limit ('max', the default for bad habits) or a target ('min') per day, week or month."""
    if target is None:
        return None
    if target <= 0:
        raise ValueError("La meta debe ser mayor que 0.")
    period = period or "dia"
    if period not in GOAL_PERIODS:
        raise ValueError(f"Periodo de meta desconocido. Opciones: {', '.join(GOAL_PERIODS)}")
    direction = direction or ("max" if polarity == "malo" else "min")
    if direction not in ("max", "min"):
        raise ValueError("La dirección de la meta es max (no pasar de) o min (llegar al menos a).")
    return {"target": float(target), "period": period, "direction": direction}


class Store:
    def __init__(self, db: Database, default_tz: str = "America/Bogota",
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.db = db
        self.default_tz = default_tz
        self.now = now

    def ensure_indexes(self) -> None:
        self.db.habits.create_index([("owner", ASCENDING), ("keys", ASCENDING)])
        self.db.entries.create_index([("owner", ASCENDING), ("habit_id", ASCENDING), ("day", ASCENDING)])
        self.db.entries.create_index([("owner", ASCENDING), ("seq", DESCENDING)])

    # --- time ------------------------------------------------------------------------------------

    def zone(self, owner: str) -> ZoneInfo:
        settings = self.db.settings.find_one({"_id": owner}) or {}
        return ZoneInfo(settings.get("timezone") or self.default_tz)

    def set_timezone(self, owner: str, name: str) -> dict:
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"Zona horaria desconocida: {name}. Usa nombres como America/Bogota.") from error
        self.db.settings.update_one({"_id": owner}, {"$set": {"timezone": name}}, upsert=True)
        return {"timezone": name, "today": self.today(owner).isoformat()}

    def local_now(self, owner: str) -> datetime:
        return self.now().astimezone(self.zone(owner))

    def today(self, owner: str) -> date:
        return self.local_now(owner).date()

    def parse_when(self, owner: str, when: str | None) -> tuple[date, int | None]:
        """'hoy', 'ayer', 'anteayer', YYYY-MM-DD, DD/MM/YYYY or a local date with HH:MM. No future dates."""
        now = self.local_now(owner)
        if not when:
            return now.date(), now.hour
        text = stats.normalize(when)
        if text in RELATIVE_DAYS:
            return now.date() - timedelta(days=RELATIVE_DAYS[text]), None
        for fmt, has_time in (("%Y-%m-%dt%H:%M", True), ("%Y-%m-%d %H:%M", True), ("%Y-%m-%d", False),
                              ("%d/%m/%Y %H:%M", True), ("%d/%m/%Y", False)):
            try:
                parsed = datetime.strptime(text, fmt)
            except ValueError:
                continue
            if parsed.date() > now.date():
                raise ValueError("No se pueden registrar fechas futuras.")
            return parsed.date(), parsed.hour if has_time else None
        raise ValueError(f"Fecha inválida: {when!r}. Usa hoy, ayer, AAAA-MM-DD o AAAA-MM-DD HH:MM.")

    # --- habits ----------------------------------------------------------------------------------

    def _keys(self, name: str, aliases: list[str] | None) -> list[str]:
        return list(dict.fromkeys(stats.normalize(n) for n in [name, *(aliases or [])] if n and n.strip()))

    def create_habit(self, owner: str, name: str, unit: str = "veces", category: str = "otro",
                     polarity: str = "neutral", aliases: list[str] | None = None, goal: dict | None = None,
                     notes: str | None = None) -> dict:
        if not name or not name.strip():
            raise ValueError("El hábito necesita un nombre.")
        if category not in CATEGORIES:
            raise ValueError(f"Categoría desconocida. Opciones: {', '.join(CATEGORIES)}")
        if polarity not in stats.POLARITIES:
            raise ValueError(f"Tipo desconocido. Opciones: {', '.join(stats.POLARITIES)}")
        keys = self._keys(name, aliases)
        clash = self.db.habits.find_one({"owner": owner, "keys": {"$in": keys}})
        if clash:
            raise ValueError(f"Ya existe el hábito «{clash['name']}» con ese nombre o alias.")
        doc = {"_id": _id(), "owner": owner, "name": name.strip(), "unit": unit or "veces", "category": category,
               "polarity": polarity, "aliases": aliases or [], "keys": keys, "goal": goal, "notes": notes,
               "archived": False, "created_at": self.now()}
        self.db.habits.insert_one(doc)
        return self._summary(owner, doc)

    def find_habit(self, owner: str, ref: str) -> dict:
        """By id, name or alias, ignoring case and accents; suggests the closest names when missing."""
        doc = self.db.habits.find_one({"owner": owner, "$or": [{"_id": ref}, {"keys": stats.normalize(ref)}]})
        if doc:
            return doc
        names = [h["name"] for h in self.db.habits.find({"owner": owner, "archived": False}, {"name": 1})]
        close = difflib.get_close_matches(ref, names, n=3, cutoff=0.5)
        hint = f" ¿Quisiste decir {', '.join(close)}?" if close else " Créalo primero con create_habit."
        raise NotFound(f"No tienes un hábito llamado «{ref}».{hint}")

    def habits(self, owner: str, include_archived: bool = False) -> dict:
        query = {"owner": owner, **({} if include_archived else {"archived": False})}
        docs = list(self.db.habits.find(query).sort("name", ASCENDING))
        return {"today": self.today(owner).isoformat(), "timezone": str(self.zone(owner)),
                "habits": [self._summary(owner, doc) for doc in docs]}

    def _entries(self, owner: str, habit_id: str) -> list[stats.Entry]:
        return [_entry(doc) for doc in self.db.entries.find({"owner": owner, "habit_id": habit_id})]

    def _summary(self, owner: str, doc: dict) -> dict:
        entries = self._entries(owner, doc["_id"])
        today = self.today(owner)
        totals = {period: stats.total(entries, *stats.period_bounds(period, today)) for period in stats.PERIODS}
        streak = stats.streaks(entries, today)
        return {**_public(doc), "totals": totals, "goal_status": stats.goal_status(entries, doc.get("goal"), today),
                "days_since_last": streak["days_since_last"], "current_streak_days": streak["current_days"]}

    def update_habit(self, owner: str, ref: str, clear_goal: bool = False, **fields: object) -> dict:
        doc = self.find_habit(owner, ref)
        changes = {key: value for key, value in fields.items() if key in HABIT_FIELDS and value is not None}
        if clear_goal:
            changes["goal"] = None
        if "category" in changes and changes["category"] not in CATEGORIES:
            raise ValueError(f"Categoría desconocida. Opciones: {', '.join(CATEGORIES)}")
        if "polarity" in changes and changes["polarity"] not in stats.POLARITIES:
            raise ValueError(f"Tipo desconocido. Opciones: {', '.join(stats.POLARITIES)}")
        if "name" in changes or "aliases" in changes:
            keys = self._keys(str(changes.get("name", doc["name"])), changes.get("aliases", doc.get("aliases")))
            clash = self.db.habits.find_one({"owner": owner, "_id": {"$ne": doc["_id"]}, "keys": {"$in": keys}})
            if clash:
                raise ValueError(f"Ya existe el hábito «{clash['name']}» con ese nombre o alias.")
            changes["keys"] = keys
        if changes:
            self.db.habits.update_one({"_id": doc["_id"]}, {"$set": changes})
        return self._summary(owner, self.db.habits.find_one({"_id": doc["_id"]}))

    def set_archived(self, owner: str, ref: str, archived: bool) -> dict:
        doc = self.find_habit(owner, ref)
        self.db.habits.update_one({"_id": doc["_id"]}, {"$set": {"archived": archived}})
        return {"habit": doc["name"], "archived": archived}

    def delete_habit(self, owner: str, ref: str) -> dict:
        doc = self.find_habit(owner, ref)
        removed = self.db.entries.delete_many({"owner": owner, "habit_id": doc["_id"]}).deleted_count
        self.db.habits.delete_one({"_id": doc["_id"]})
        return {"deleted": doc["name"], "entries_removed": removed}

    # --- entries ---------------------------------------------------------------------------------

    def log(self, owner: str, ref: str, value: float = 1, when: str | None = None, detail: str | None = None,
            note: str | None = None) -> dict:
        """Record an occurrence and return the habit's updated totals, so the agent can give feedback."""
        doc = self.find_habit(owner, ref)
        if value <= 0:
            raise ValueError("La cantidad debe ser mayor que 0.")
        day, hour = self.parse_when(owner, when)
        entry = {"_id": _id(), "owner": owner, "habit_id": doc["_id"], "day": day.isoformat(), "hour": hour,
                 "value": float(value), "detail": detail.strip() if detail else None, "note": note,
                 "created_at": self.now(), "seq": time.time_ns()}
        self.db.entries.insert_one(entry)
        if doc.get("archived"):
            self.db.habits.update_one({"_id": doc["_id"]}, {"$set": {"archived": False}})
        logged = {k: v for k, v in entry.items() if k not in ("owner", "_id", "seq")}
        return {"logged": {**logged, "id": entry["_id"]},
                "habit": self._summary(owner, self.db.habits.find_one({"_id": doc["_id"]}))}

    def entries(self, owner: str, ref: str | None = None, start: str | None = None, end: str | None = None,
                limit: int = 50) -> list[dict]:
        query: dict = {"owner": owner}
        if ref:
            query["habit_id"] = self.find_habit(owner, ref)["_id"]
        if start or end:
            query["day"] = {**({"$gte": self.parse_when(owner, start)[0].isoformat()} if start else {}),
                            **({"$lte": self.parse_when(owner, end)[0].isoformat()} if end else {})}
        names = {h["_id"]: h["name"] for h in self.db.habits.find({"owner": owner}, {"name": 1})}
        cursor = self.db.entries.find(query).sort([("day", DESCENDING), ("seq", DESCENDING)]).limit(limit)
        return [{"id": e["_id"], "habit": names.get(e["habit_id"]), "day": e["day"], "hour": e.get("hour"),
                 "value": e["value"], "detail": e.get("detail"), "note": e.get("note")} for e in cursor]

    def delete_entry(self, owner: str, entry_id: str | None = None) -> dict:
        """Delete one entry, or the most recently recorded one when no id is given (deshacer). `seq` orders
        entries by insertion even when two share the same timestamp."""
        query = {"owner": owner, **({"_id": entry_id} if entry_id else {})}
        doc = next(iter(self.db.entries.find(query).sort("seq", DESCENDING).limit(1)), None)
        if doc is None:
            raise NotFound("No hay ese registro para borrar.")
        self.db.entries.delete_one({"_id": doc["_id"]})
        habit = self.db.habits.find_one({"_id": doc["habit_id"]}, {"name": 1})
        return {"deleted": doc["_id"], "habit": habit["name"] if habit else None, "day": doc["day"],
                "value": doc["value"], "detail": doc.get("detail")}

    # --- analysis --------------------------------------------------------------------------------

    def habit_stats(self, owner: str, ref: str, year: int | None = None) -> dict:
        doc = self.find_habit(owner, ref)
        entries = self._entries(owner, doc["_id"])
        today = self.today(owner)
        year = year or today.year
        return {
            "habit": doc["name"], "unit": doc["unit"], "polarity": doc["polarity"], "today": today.isoformat(),
            "comparisons": [stats.compare(entries, period, today, doc["polarity"]) for period in stats.PERIODS],
            "goal": stats.goal_status(entries, doc.get("goal"), today),
            "streaks": stats.streaks(entries, today),
            "year": year, **stats.distributions([e for e in entries if e.day.year == year]),
        }

    def series(self, owner: str, ref: str, year: int | None = None, granularity: str = "mes") -> dict:
        doc = self.find_habit(owner, ref)
        year = year or self.today(owner).year
        return {"habit": doc["name"], "unit": doc["unit"], "polarity": doc["polarity"], "year": year,
                "granularity": granularity, "goal": doc.get("goal"),
                "series": stats.series(self._entries(owner, doc["_id"]), year, granularity)}

    def year_summary(self, owner: str, year: int | None = None) -> dict:
        year = year or self.today(owner).year
        habits = list(self.db.habits.find({"owner": owner}).sort("name", ASCENDING))
        items = []
        for doc in habits:
            summary = stats.year_summary(self._entries(owner, doc["_id"]), year)
            if not summary["total"] and not summary["previous_year_total"]:
                continue
            change = stats.trend(summary["total"], summary["previous_year_total"])
            items.append({"habit": doc["name"], "unit": doc["unit"], "polarity": doc["polarity"],
                          "category": doc["category"], **summary, "vs_previous_year": change,
                          "verdict": stats.verdict(doc["polarity"], change["trend"])})
        return {"year": year, "habits": items,
                "improved": [i["habit"] for i in items if i["verdict"] == "mejora"],
                "worsened": [i["habit"] for i in items if i["verdict"] == "empeora"]}
