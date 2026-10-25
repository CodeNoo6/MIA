"""Owner-scoped persistence for Cat Life on MongoDB.

Every read and write is filtered by `owner`, the data space of the MIA user the MCP receives from LibreChat:
their own user id, or their household's id when they share cats with family (see `catlife.family`). The only
reads without an owner are the public share and calendar tokens, which are random and resolve to exactly one
cat or one space.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

from catlife import care

CAT_FIELDS = ("name", "color", "gender", "breed", "species", "birth_date", "age_months", "weight_kg",
              "sterilized", "microchip", "notes")
CASCADE = ("vaccines", "records", "weights", "conditions", "appointments", "reminders", "photos")
LABELS = {
    "cats": "un gato", "vaccines": "una vacuna", "records": "un registro clínico", "conditions": "una condición",
    "appointments": "una cita", "reminders": "un recordatorio", "vets": "un veterinario",
}
UPLOAD_TTL = timedelta(minutes=30)
MAX_PHOTO_BYTES = 5 * 1024 * 1024


class NotFound(ValueError):
    pass


def _id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: str | None) -> str | None:
    return care.parse_date(value).isoformat() if value else None


def _public(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    out = {key: value for key, value in doc.items() if key not in ("_id", "owner", "data")}
    out["id"] = doc["_id"]
    return out


def _clean(fields: dict) -> dict:
    return {key: value for key, value in fields.items() if value is not None}


class Store:
    def __init__(self, db: Database, today: Callable[[], date] = date.today):
        self.db = db
        self.today = today

    def ensure_indexes(self) -> None:
        for name in ("cats", "vaccines", "records", "weights", "conditions", "appointments", "reminders", "vets"):
            self.db[name].create_index([("owner", ASCENDING), ("cat_id", ASCENDING)])
        self.db.cats.create_index("share_token", unique=True, sparse=True)
        self.db.users.create_index("calendar_token", unique=True, sparse=True)
        self.db.uploads.create_index("expires_at", expireAfterSeconds=0)

    # --- generic helpers -------------------------------------------------------------------------

    def _insert(self, collection: str, owner: str, fields: dict) -> dict:
        doc = {"_id": _id(), "owner": owner, "created_at": _now(), **_clean(fields)}
        self.db[collection].insert_one(doc)
        return _public(doc)

    def _get(self, collection: str, owner: str, doc_id: str) -> dict:
        doc = self.db[collection].find_one({"_id": doc_id, "owner": owner})
        if doc is None:
            raise NotFound(f"No existe {LABELS[collection]} con id {doc_id} para este usuario.")
        return doc

    def _list(self, collection: str, owner: str, query: dict | None = None, sort: str = "created_at",
              direction: int = ASCENDING) -> list[dict]:
        cursor = self.db[collection].find({"owner": owner, **(query or {})}).sort(sort, direction)
        return [_public(doc) for doc in cursor]

    def _update(self, collection: str, owner: str, doc_id: str, fields: dict) -> dict:
        self._get(collection, owner, doc_id)
        changes = _clean(fields)
        if changes:
            self.db[collection].update_one({"_id": doc_id, "owner": owner},
                                           {"$set": {**changes, "updated_at": _now()}})
        return _public(self._get(collection, owner, doc_id))

    def _delete(self, collection: str, owner: str, doc_id: str) -> dict:
        if self.db[collection].delete_one({"_id": doc_id, "owner": owner}).deleted_count == 0:
            raise NotFound(f"No existe {LABELS[collection]} con id {doc_id} para este usuario.")
        return {"deleted": doc_id}

    def _cat_query(self, cat_id: str | None) -> dict:
        return {"cat_id": cat_id} if cat_id else {}

    def require_cat(self, owner: str, cat_id: str) -> dict:
        return self._get("cats", owner, cat_id)

    # --- cats ------------------------------------------------------------------------------------

    def add_cat(self, owner: str, **fields: object) -> dict:
        if not fields.get("name"):
            raise ValueError("El gato necesita un nombre.")
        fields["birth_date"] = _iso(fields.get("birth_date"))
        fields.setdefault("species", "Felino")
        fields["breed"] = fields.get("breed") or "Mestizo"
        cat = self._insert("cats", owner, {key: fields.get(key) for key in CAT_FIELDS})
        if fields.get("weight_kg"):
            self.add_weight(owner, cat["id"], float(fields["weight_kg"]), None, "Registro inicial")
        return self.cat(owner, cat["id"])

    def cat(self, owner: str, cat_id: str) -> dict:
        cat = _public(self.require_cat(owner, cat_id))
        return {**cat, **self._age(cat)}

    def cats(self, owner: str) -> list[dict]:
        return [{**cat, **self._age(cat)} for cat in self._list("cats", owner)]

    def _age(self, cat: dict) -> dict:
        months = cat.get("age_months")
        if cat.get("birth_date"):
            months = care.age_in_months(care.parse_date(cat["birth_date"]), self.today())
        if months is None:
            return {}
        return {"age_months": months, "human_age": care.human_age(int(months))}

    def update_cat(self, owner: str, cat_id: str, **fields: object) -> dict:
        if fields.get("birth_date"):
            fields["birth_date"] = _iso(fields["birth_date"])
        previous = self.require_cat(owner, cat_id)
        self._update("cats", owner, cat_id, {key: fields.get(key) for key in CAT_FIELDS})
        weight = fields.get("weight_kg")
        if weight is not None and weight != previous.get("weight_kg"):
            self.add_weight(owner, cat_id, float(weight), None, "Actualización de perfil")
        return self.cat(owner, cat_id)

    def delete_cat(self, owner: str, cat_id: str) -> dict:
        cat = self.require_cat(owner, cat_id)
        removed = {name: self.db[name].delete_many({"owner": owner, "cat_id": cat_id}).deleted_count
                   for name in CASCADE}
        self.db.cats.delete_one({"_id": cat_id, "owner": owner})
        return {"deleted": cat_id, "name": cat["name"], "removed": removed}

    # --- vaccines --------------------------------------------------------------------------------

    def add_vaccine(self, owner: str, cat_id: str, name: str, applied: str | None, frequency: str,
                    total_doses: int = 1, veterinarian: str | None = None, notes: str | None = None,
                    next_due: str | None = None) -> dict:
        self.require_cat(owner, cat_id)
        history = []
        next_dose = name
        if applied:
            applied_date = care.parse_date(applied)
            computed = care.next_due_date(applied_date, frequency)
            next_due = _iso(next_due) or (computed.isoformat() if computed else None)
            history = [{"date": applied_date.isoformat(), "dose": 1, "name": name, "next_due": next_due,
                        "veterinarian": veterinarian, "notes": notes}]
            next_dose = care.next_dose_name(name) if next_due else None
        else:
            care.next_due_date(self.today(), frequency)
            next_due = _iso(next_due)
        return self._insert("vaccines", owner, {
            "cat_id": cat_id, "name": name, "frequency": frequency, "total_doses": total_doses,
            "doses_applied": len(history), "last_applied": history[0]["date"] if history else None,
            "next_due": next_due, "next_dose": next_dose, "veterinarian": veterinarian, "notes": notes,
            "history": history,
        })

    def vaccines(self, owner: str, cat_id: str | None = None) -> list[dict]:
        if cat_id:
            self.require_cat(owner, cat_id)
        return self._list("vaccines", owner, self._cat_query(cat_id), "next_due")

    def apply_dose(self, owner: str, vaccine_id: str, applied: str, veterinarian: str | None = None,
                   notes: str | None = None, next_due: str | None = None) -> dict:
        """Record a dose like the app's 'completar y renovar': history grows, the next date follows the
        frequency unless one is given, and the pending dose advances 1era → 2da → 3era → Refuerzo."""
        vaccine = self._get("vaccines", owner, vaccine_id)
        applied_date = care.parse_date(applied)
        computed = care.next_due_date(applied_date, vaccine["frequency"])
        due = _iso(next_due) or (computed.isoformat() if computed else None)
        dose = vaccine.get("doses_applied", 0) + 1
        label = vaccine.get("next_dose") or vaccine["name"]
        entry = {"date": applied_date.isoformat(), "dose": dose, "name": label, "next_due": due,
                 "veterinarian": veterinarian, "notes": notes}
        changes = _clean({"doses_applied": dose, "last_applied": entry["date"], "veterinarian": veterinarian,
                          "updated_at": _now()})
        self.db.vaccines.update_one({"_id": vaccine_id, "owner": owner}, {
            "$push": {"history": entry},
            "$set": {**changes, "next_due": due, "next_dose": care.next_dose_name(label) if due else None},
        })
        return _public(self._get("vaccines", owner, vaccine_id))

    def delete_vaccine(self, owner: str, vaccine_id: str) -> dict:
        return self._delete("vaccines", owner, vaccine_id)

    # --- clinical history ------------------------------------------------------------------------

    def add_record(self, owner: str, cat_id: str, **fields: object) -> dict:
        self.require_cat(owner, cat_id)
        kind = str(fields.get("record_type") or "consulta")
        if kind not in care.RECORD_TYPES:
            raise ValueError(f"Tipo desconocido. Opciones: {', '.join(care.RECORD_TYPES)}")
        fields["date"] = _iso(str(fields.get("date") or self.today().isoformat()))
        fields["next_appointment"] = _iso(fields.get("next_appointment"))
        medications = [{**med, "id": _id()} for med in fields.pop("medications", None) or []]
        record = self._insert("records", owner, {"cat_id": cat_id, **fields, "medications": medications})
        if fields.get("weight_kg"):
            self.add_weight(owner, cat_id, float(fields["weight_kg"]), fields["date"],
                            f"Registrado en {care.RECORD_TYPES[kind]}")
        if fields.get("next_appointment"):
            self.add_appointment(owner, cat_id, fields["next_appointment"], None,
                                 f"Seguimiento: {fields.get('reason') or care.RECORD_TYPES[kind]}",
                                 fields.get("veterinarian"), fields.get("clinic"))
        return record

    def records(self, owner: str, cat_id: str, record_type: str | None = None) -> list[dict]:
        self.require_cat(owner, cat_id)
        query = {"cat_id": cat_id, **({"record_type": record_type} if record_type else {})}
        return self._list("records", owner, query, "date", DESCENDING)

    def delete_record(self, owner: str, record_id: str) -> dict:
        return self._delete("records", owner, record_id)

    def add_weight(self, owner: str, cat_id: str, weight_kg: float, when: str | None, notes: str | None) -> dict:
        self.require_cat(owner, cat_id)
        if weight_kg <= 0:
            raise ValueError("El peso debe ser mayor que 0.")
        day = _iso(when) or self.today().isoformat()
        self.db.cats.update_one({"_id": cat_id, "owner": owner}, {"$set": {"weight_kg": weight_kg}})
        return self._insert("weights", owner, {"cat_id": cat_id, "weight_kg": weight_kg, "date": day, "notes": notes})

    def weights(self, owner: str, cat_id: str) -> list[dict]:
        self.require_cat(owner, cat_id)
        return self._list("weights", owner, {"cat_id": cat_id}, "date")

    def add_condition(self, owner: str, cat_id: str, **fields: object) -> dict:
        self.require_cat(owner, cat_id)
        if fields.get("condition_type") not in care.CONDITION_TYPES:
            raise ValueError(f"Tipo de condición desconocido. Opciones: {', '.join(care.CONDITION_TYPES)}")
        if fields.get("severity") not in care.SEVERITIES:
            raise ValueError(f"Severidad desconocida. Opciones: {', '.join(care.SEVERITIES)}")
        fields["diagnosed"] = _iso(fields.get("diagnosed"))
        return self._insert("conditions", owner, {"cat_id": cat_id, "active": True, **fields})

    def conditions(self, owner: str, cat_id: str) -> list[dict]:
        self.require_cat(owner, cat_id)
        return self._list("conditions", owner, {"cat_id": cat_id})

    def update_condition(self, owner: str, condition_id: str, active: bool | None, treatment: str | None,
                         notes: str | None) -> dict:
        changes = {"active": active, "treatment": treatment, "notes": notes}
        return self._update("conditions", owner, condition_id, changes)

    def add_appointment(self, owner: str, cat_id: str, day: str, time: str | None, reason: str,
                        veterinarian: str | None = None, clinic: str | None = None,
                        notes: str | None = None) -> dict:
        self.require_cat(owner, cat_id)
        return self._insert("appointments", owner, {
            "cat_id": cat_id, "date": _iso(day), "time": time, "reason": reason, "veterinarian": veterinarian,
            "clinic": clinic, "notes": notes, "status": "programada",
        })

    def appointments(self, owner: str, cat_id: str | None = None) -> list[dict]:
        return self._list("appointments", owner, self._cat_query(cat_id), "date")

    def update_appointment(self, owner: str, appointment_id: str, status: str | None, day: str | None,
                           time: str | None, notes: str | None) -> dict:
        if status and status not in care.APPOINTMENT_STATUSES:
            raise ValueError(f"Estado desconocido. Opciones: {', '.join(care.APPOINTMENT_STATUSES)}")
        return self._update("appointments", owner, appointment_id,
                            {"status": status, "date": _iso(day), "time": time, "notes": notes})

    def add_reminder(self, owner: str, cat_id: str, title: str, due: str | None, repeat: str | None,
                     notes: str | None, kind: str = "otro", product: str | None = None,
                     last_done: str | None = None) -> dict:
        """`due` wins; otherwise the date follows `repeat` from `last_done`, or today when neither is known."""
        self.require_cat(owner, cat_id)
        if kind not in care.REMINDER_KINDS:
            raise ValueError(f"Tipo de recordatorio desconocido. Opciones: {', '.join(care.REMINDER_KINDS)}")
        following = care.next_due_date(care.parse_date(last_done), repeat or "") if last_done else None
        if repeat:
            care.next_due_date(self.today(), repeat)
        due = due or (following.isoformat() if following else self.today().isoformat())
        return self._insert("reminders", owner, {"cat_id": cat_id, "kind": kind, "title": title, "due": _iso(due),
                                                 "repeat": repeat, "product": product, "notes": notes,
                                                 "completed": False})

    def reminders(self, owner: str, cat_id: str | None = None, include_completed: bool = False) -> list[dict]:
        query = {**self._cat_query(cat_id), **({} if include_completed else {"completed": False})}
        return self._list("reminders", owner, query, "due")

    def update_reminder(self, owner: str, reminder_id: str, title: str | None, due: str | None,
                        repeat: str | None, product: str | None, notes: str | None) -> dict:
        if repeat:
            care.next_due_date(self.today(), repeat)
        return self._update("reminders", owner, reminder_id, {"title": title, "due": _iso(due), "repeat": repeat,
                                                              "product": product, "notes": notes})

    def delete_reminder(self, owner: str, reminder_id: str) -> dict:
        return self._delete("reminders", owner, reminder_id)

    def complete_reminder(self, owner: str, reminder_id: str, done: str | None = None) -> dict:
        """Mark it done on `done` (today by default); a repeating one schedules the next from that date,
        so a late dose does not leave the following one overdue."""
        reminder = self._get("reminders", owner, reminder_id)
        done_date = care.parse_date(done) if done else self.today()
        self._update("reminders", owner, reminder_id, {"completed": True, "done": done_date.isoformat()})
        nxt = care.next_due_date(done_date, reminder.get("repeat") or "")
        follow = None
        if nxt:
            follow = self.add_reminder(owner, reminder["cat_id"], reminder["title"], nxt.isoformat(),
                                       reminder["repeat"], reminder.get("notes"), reminder.get("kind", "otro"),
                                       reminder.get("product"))
        return {"completed": reminder_id, "title": reminder["title"], "cat_id": reminder["cat_id"],
                "done": done_date.isoformat(), "next": follow}

    def care_plan(self, owner: str, cat_id: str) -> dict:
        """Suggested preventive reminders for the cat's age, flagging the kinds already scheduled."""
        cat = self.cat(owner, cat_id)
        scheduled = {doc.get("kind") for doc in self.db.reminders.find(
            {"owner": owner, "cat_id": cat_id, "completed": False}, {"kind": 1})}
        suggestions = [{**item, "already_scheduled": item["kind"] in scheduled}
                       for item in care.care_plan(cat.get("age_months"))]
        return {"cat": cat["name"], "age_months": cat.get("age_months"), "suggestions": suggestions,
                "pending_vaccines": [v for v in self.vaccines(owner, cat_id) if v.get("next_due")],
                "note": "Plan orientativo. Confirma productos y frecuencias con el veterinario del gato."}

    def add_vet(self, owner: str, **fields: object) -> dict:
        if fields.get("primary"):
            self.db.vets.update_many({"owner": owner}, {"$set": {"primary": False}})
        return self._insert("vets", owner, fields)

    def vets(self, owner: str) -> list[dict]:
        return self._list("vets", owner, sort="name")

    def delete_vet(self, owner: str, vet_id: str) -> dict:
        return self._delete("vets", owner, vet_id)

    # --- agenda and summaries --------------------------------------------------------------------

    def agenda(self, owner: str, days: int | None = 30, cat_id: str | None = None) -> list[dict]:
        """Overdue and upcoming vaccines, appointments and reminders, oldest first."""
        today = self.today()
        horizon = (today + timedelta(days=days)).isoformat() if days is not None else "9999-12-31"
        names = {cat["_id"]: cat["name"] for cat in self.db.cats.find({"owner": owner}, {"name": 1})}
        base = {"owner": owner, **self._cat_query(cat_id)}
        items = [
            *({"kind": "vacuna", "id": doc["_id"], "cat_id": doc["cat_id"], "date": doc["next_due"],
               "title": f"Vacuna {doc.get('next_dose') or doc['name']}", "detail": doc.get("veterinarian")}
              for doc in self.db.vaccines.find({**base, "next_due": {"$ne": None, "$lte": horizon}})),
            *({"kind": "cita", "id": doc["_id"], "cat_id": doc["cat_id"], "date": doc["date"],
               "time": doc.get("time"), "title": f"Cita: {doc['reason']}",
               "detail": ", ".join(filter(None, (doc.get("veterinarian"), doc.get("clinic"))))}
              for doc in self.db.appointments.find({**base, "status": {"$in": ["programada", "confirmada"]},
                                                    "date": {"$lte": horizon}})),
            *({"kind": doc.get("kind", "otro"), "id": doc["_id"], "cat_id": doc["cat_id"], "date": doc["due"],
               "title": doc["title"], "detail": ", ".join(filter(None, (doc.get("product"), doc.get("notes"))))}
              for doc in self.db.reminders.find({**base, "completed": False, "due": {"$lte": horizon}})),
        ]
        for item in items:
            item["cat"] = names.get(item["cat_id"], "")
            item["overdue"] = item["date"] < today.isoformat()
        return sorted(items, key=lambda item: (item["date"], item.get("time") or ""))

    def health_summary(self, owner: str, cat_id: str) -> dict:
        cat = self.cat(owner, cat_id)
        today = self.today().isoformat()
        records = self.records(owner, cat_id)
        weights = self.weights(owner, cat_id)
        medications = [
            {**med, "record_date": record["date"]}
            for record in records for med in record.get("medications", [])
            if med.get("active", True) and (not med.get("end_date") or _iso(med["end_date"]) >= today)
        ]
        agenda = self.agenda(owner, None, cat_id)
        return {
            "cat": cat,
            "total_visits": len(records),
            "last_visit": records[0] if records else None,
            "current_weight_kg": weights[-1]["weight_kg"] if weights else cat.get("weight_kg"),
            "weight_trend": [{"date": w["date"], "weight_kg": w["weight_kg"]} for w in weights[-6:]],
            "active_conditions": [c for c in self.conditions(owner, cat_id) if c.get("active")],
            "active_medications": medications,
            "overdue": [item for item in agenda if item["overdue"]],
            "upcoming": [item for item in agenda if not item["overdue"]][:10],
        }

    # --- sharing ---------------------------------------------------------------------------------

    def share_token(self, owner: str, cat_id: str, rotate: bool = False) -> str:
        cat = self.require_cat(owner, cat_id)
        if cat.get("share_token") and not rotate:
            return cat["share_token"]
        token = secrets.token_urlsafe(16)
        self.db.cats.update_one({"_id": cat_id, "owner": owner}, {"$set": {"share_token": token}})
        return token

    def stop_sharing(self, owner: str, cat_id: str) -> dict:
        self.require_cat(owner, cat_id)
        self.db.cats.update_one({"_id": cat_id, "owner": owner}, {"$unset": {"share_token": ""}})
        return {"cat_id": cat_id, "shared": False}

    def public_card(self, token: str) -> dict | None:
        """The read-only carné a share token unlocks: the cat profile and its vaccines, nothing clinical."""
        cat = self.db.cats.find_one({"share_token": token})
        if cat is None:
            return None
        owner = cat["owner"]
        vaccines = self._list("vaccines", owner, {"cat_id": cat["_id"]}, "next_due")
        public = {key: value for key, value in _public(cat).items() if key not in ("share_token", "notes")}
        has_photo = self.db.photos.count_documents({"cat_id": cat["_id"], "owner": owner}) > 0
        return {"cat": {**public, **self._age(public), "has_photo": has_photo}, "vaccines": vaccines,
                "generated": self.today().isoformat()}

    def calendar_token(self, owner: str, rotate: bool = False) -> str:
        user = self.db.users.find_one({"_id": owner}) or {}
        if user.get("calendar_token") and not rotate:
            return user["calendar_token"]
        token = secrets.token_urlsafe(16)
        self.db.users.update_one({"_id": owner}, {"$set": {"calendar_token": token}}, upsert=True)
        return token

    def calendar_owner(self, token: str) -> str | None:
        user = self.db.users.find_one({"calendar_token": token})
        return user["_id"] if user else None

    # --- photos ----------------------------------------------------------------------------------

    def photo_upload_token(self, owner: str, cat_id: str) -> str:
        self.require_cat(owner, cat_id)
        token = secrets.token_urlsafe(16)
        self.db.uploads.insert_one({"_id": token, "owner": owner, "cat_id": cat_id,
                                    "expires_at": _now() + UPLOAD_TTL})
        return token

    def upload_target(self, token: str) -> dict | None:
        upload = self.db.uploads.find_one({"_id": token})
        if upload is None:
            return None
        expires = upload["expires_at"]
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < _now():
            return None
        cat = self.db.cats.find_one({"_id": upload["cat_id"], "owner": upload["owner"]}, {"name": 1})
        return {"owner": upload["owner"], "cat_id": upload["cat_id"], "name": cat["name"]} if cat else None

    def save_photo(self, token: str, data: bytes, content_type: str) -> dict:
        target = self.upload_target(token)
        if target is None:
            raise NotFound("El enlace para subir la foto venció. Pide uno nuevo en el chat.")
        if not content_type.startswith("image/"):
            raise ValueError("El archivo debe ser una imagen.")
        if len(data) > MAX_PHOTO_BYTES:
            raise ValueError("La foto supera 5 MB.")
        self.db.photos.replace_one({"_id": target["cat_id"]}, {
            "_id": target["cat_id"], "owner": target["owner"], "cat_id": target["cat_id"],
            "content_type": content_type, "data": data, "updated_at": _now()}, upsert=True)
        self.db.uploads.delete_one({"_id": token})
        return target

    def photo(self, cat_id: str) -> dict | None:
        return self.db.photos.find_one({"_id": cat_id})
