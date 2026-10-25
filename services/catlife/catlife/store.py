"""Owner-scoped persistence for the pet agents (Agente de Cuidador Felino and Canino) on MongoDB.

Every read and write is filtered by `owner`, the data space of the MIA user the MCP receives from LibreChat:
their own user id, or their household's id when they share pets with family (see `catlife.family`). The only
reads without an owner are the public share and calendar tokens, which are random and resolve to exactly one
pet or one space. Each pet carries its `species`, so an agent can be scoped to cats or to dogs while the
household, its calendar and its activity stay shared.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

from catlife import care

PET_FIELDS = ("name", "species", "color", "gender", "breed", "size", "birth_date", "age_months", "weight_kg",
              "sterilized", "microchip", "notes")
PET_LINKED = ("vaccines", "records", "weights", "conditions", "appointments", "reminders", "photos", "activity")
CASCADE = ("vaccines", "records", "weights", "conditions", "appointments", "reminders", "photos")
LABELS = {
    "pets": "una mascota", "vaccines": "una vacuna", "records": "un registro clínico", "conditions": "una condición",
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

    def migrate(self) -> None:
        """One-time move from the cat-only schema: `cats` becomes `pets`, `cat_id` becomes `pet_id`, and pets
        without a known species are cats. Idempotent."""
        names = set(self.db.list_collection_names())
        if "cats" in names and "pets" not in names:
            self.db.cats.rename("pets")
        for name in PET_LINKED:
            self.db[name].update_many({"cat_id": {"$exists": True}}, {"$rename": {"cat_id": "pet_id"}})
        self.db.pets.update_many({"species": {"$nin": list(care.SPECIES)}}, {"$set": {"species": care.DEFAULT_SPECIES}})

    def ensure_indexes(self) -> None:
        self.migrate()
        for name in ("pets", "vaccines", "records", "weights", "conditions", "appointments", "reminders", "vets"):
            self.db[name].create_index([("owner", ASCENDING), ("pet_id", ASCENDING)])
        self.db.pets.create_index("share_token", unique=True, sparse=True)
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

    def _scope(self, owner: str, pet_id: str | None, species: str | None = None) -> dict:
        """Query fragment for one pet, or for every pet of one species, or for everything."""
        if pet_id:
            return {"pet_id": pet_id}
        if species:
            return {"pet_id": {"$in": [doc["_id"] for doc in self.db.pets.find({"owner": owner, "species": species},
                                                                              {"_id": 1})]}}
        return {}

    def require_pet(self, owner: str, pet_id: str, species: str | None = None) -> dict:
        pet = self._get("pets", owner, pet_id)
        if species and pet.get("species", care.DEFAULT_SPECIES) != species:
            raise NotFound(f"Esa mascota no es un {care.SPECIES[species][0]}; ábrela con el agente de su especie.")
        return pet

    def species_of(self, owner: str, collection: str, doc_id: str) -> str | None:
        """Species of the pet a vaccine, record, reminder, appointment or condition belongs to."""
        doc = self.db[collection].find_one({"_id": doc_id, "owner": owner}, {"pet_id": 1})
        pet = self.db.pets.find_one({"_id": doc["pet_id"], "owner": owner}, {"species": 1}) if doc else None
        return pet.get("species", care.DEFAULT_SPECIES) if pet else None

    # --- pets ------------------------------------------------------------------------------------

    def add_pet(self, owner: str, **fields: object) -> dict:
        if not fields.get("name"):
            raise ValueError("La mascota necesita un nombre.")
        fields["birth_date"] = _iso(fields.get("birth_date"))
        fields["species"] = care.species_key(fields.get("species"))
        if fields["species"] == "perro":
            fields["size"] = care.dog_size(None, fields.get("size")) if fields.get("size") else None
        else:
            fields["size"] = None
        fields["breed"] = fields.get("breed") or "Mestizo"
        pet = self._insert("pets", owner, {key: fields.get(key) for key in PET_FIELDS})
        if fields.get("weight_kg"):
            self.add_weight(owner, pet["id"], float(fields["weight_kg"]), None, "Registro inicial")
        return self.pet(owner, pet["id"])

    def pet(self, owner: str, pet_id: str) -> dict:
        pet = _public(self.require_pet(owner, pet_id))
        return {**pet, **self._profile(pet)}

    def pets(self, owner: str, species: str | None = None) -> list[dict]:
        query = {"species": species} if species else {}
        return [{**pet, **self._profile(pet)} for pet in self._list("pets", owner, query)]

    def _size(self, pet: dict) -> str | None:
        if pet.get("species") != "perro":
            return None
        return care.dog_size(pet.get("weight_kg"), pet.get("size"))

    def _age(self, pet: dict) -> dict:
        months = pet.get("age_months")
        if pet.get("birth_date"):
            months = care.age_in_months(care.parse_date(pet["birth_date"]), self.today())
        if months is None:
            return {}
        species = pet.get("species", care.DEFAULT_SPECIES)
        return {"age_months": months, "human_age": care.human_age(int(months), species, self._size(pet))}

    def _profile(self, pet: dict) -> dict:
        """Derived facts: age, human age and, for dogs, the size implied by the weight when none was given."""
        size = self._size(pet)
        return {**self._age(pet), **({"size": size} if size else {})}

    def update_pet(self, owner: str, pet_id: str, **fields: object) -> dict:
        if fields.get("birth_date"):
            fields["birth_date"] = _iso(fields["birth_date"])
        if fields.get("size"):
            fields["size"] = care.dog_size(None, str(fields["size"]))
        fields.pop("species", None)
        previous = self.require_pet(owner, pet_id)
        self._update("pets", owner, pet_id, {key: fields.get(key) for key in PET_FIELDS})
        weight = fields.get("weight_kg")
        if weight is not None and weight != previous.get("weight_kg"):
            self.add_weight(owner, pet_id, float(weight), None, "Actualización de perfil")
        return self.pet(owner, pet_id)

    def delete_pet(self, owner: str, pet_id: str) -> dict:
        pet = self.require_pet(owner, pet_id)
        removed = {name: self.db[name].delete_many({"owner": owner, "pet_id": pet_id}).deleted_count
                   for name in CASCADE}
        self.db.pets.delete_one({"_id": pet_id, "owner": owner})
        return {"deleted": pet_id, "name": pet["name"], "removed": removed}

    # --- vaccines --------------------------------------------------------------------------------

    def add_vaccine(self, owner: str, pet_id: str, name: str, applied: str | None, frequency: str,
                    total_doses: int = 1, veterinarian: str | None = None, notes: str | None = None,
                    next_due: str | None = None) -> dict:
        self.require_pet(owner, pet_id)
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
            "pet_id": pet_id, "name": name, "frequency": frequency, "total_doses": total_doses,
            "doses_applied": len(history), "last_applied": history[0]["date"] if history else None,
            "next_due": next_due, "next_dose": next_dose, "veterinarian": veterinarian, "notes": notes,
            "history": history,
        })

    def vaccines(self, owner: str, pet_id: str | None = None, species: str | None = None) -> list[dict]:
        if pet_id:
            self.require_pet(owner, pet_id)
        return self._list("vaccines", owner, self._scope(owner, pet_id, species), "next_due")

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

    def add_record(self, owner: str, pet_id: str, **fields: object) -> dict:
        self.require_pet(owner, pet_id)
        kind = str(fields.get("record_type") or "consulta")
        if kind not in care.RECORD_TYPES:
            raise ValueError(f"Tipo desconocido. Opciones: {', '.join(care.RECORD_TYPES)}")
        fields["date"] = _iso(str(fields.get("date") or self.today().isoformat()))
        fields["next_appointment"] = _iso(fields.get("next_appointment"))
        medications = [{**med, "id": _id()} for med in fields.pop("medications", None) or []]
        record = self._insert("records", owner, {"pet_id": pet_id, **fields, "medications": medications})
        if fields.get("weight_kg"):
            self.add_weight(owner, pet_id, float(fields["weight_kg"]), fields["date"],
                            f"Registrado en {care.RECORD_TYPES[kind]}")
        if fields.get("next_appointment"):
            self.add_appointment(owner, pet_id, fields["next_appointment"], None,
                                 f"Seguimiento: {fields.get('reason') or care.RECORD_TYPES[kind]}",
                                 fields.get("veterinarian"), fields.get("clinic"))
        return record

    def records(self, owner: str, pet_id: str, record_type: str | None = None) -> list[dict]:
        self.require_pet(owner, pet_id)
        query = {"pet_id": pet_id, **({"record_type": record_type} if record_type else {})}
        return self._list("records", owner, query, "date", DESCENDING)

    def delete_record(self, owner: str, record_id: str) -> dict:
        return self._delete("records", owner, record_id)

    def add_weight(self, owner: str, pet_id: str, weight_kg: float, when: str | None, notes: str | None) -> dict:
        self.require_pet(owner, pet_id)
        if weight_kg <= 0:
            raise ValueError("El peso debe ser mayor que 0.")
        day = _iso(when) or self.today().isoformat()
        self.db.pets.update_one({"_id": pet_id, "owner": owner}, {"$set": {"weight_kg": weight_kg}})
        return self._insert("weights", owner, {"pet_id": pet_id, "weight_kg": weight_kg, "date": day, "notes": notes})

    def weights(self, owner: str, pet_id: str) -> list[dict]:
        self.require_pet(owner, pet_id)
        return self._list("weights", owner, {"pet_id": pet_id}, "date")

    def add_condition(self, owner: str, pet_id: str, **fields: object) -> dict:
        self.require_pet(owner, pet_id)
        if fields.get("condition_type") not in care.CONDITION_TYPES:
            raise ValueError(f"Tipo de condición desconocido. Opciones: {', '.join(care.CONDITION_TYPES)}")
        if fields.get("severity") not in care.SEVERITIES:
            raise ValueError(f"Severidad desconocida. Opciones: {', '.join(care.SEVERITIES)}")
        fields["diagnosed"] = _iso(fields.get("diagnosed"))
        return self._insert("conditions", owner, {"pet_id": pet_id, "active": True, **fields})

    def conditions(self, owner: str, pet_id: str) -> list[dict]:
        self.require_pet(owner, pet_id)
        return self._list("conditions", owner, {"pet_id": pet_id})

    def update_condition(self, owner: str, condition_id: str, active: bool | None, treatment: str | None,
                         notes: str | None) -> dict:
        changes = {"active": active, "treatment": treatment, "notes": notes}
        return self._update("conditions", owner, condition_id, changes)

    def add_appointment(self, owner: str, pet_id: str, day: str, time: str | None, reason: str,
                        veterinarian: str | None = None, clinic: str | None = None,
                        notes: str | None = None) -> dict:
        self.require_pet(owner, pet_id)
        return self._insert("appointments", owner, {
            "pet_id": pet_id, "date": _iso(day), "time": time, "reason": reason, "veterinarian": veterinarian,
            "clinic": clinic, "notes": notes, "status": "programada",
        })

    def appointments(self, owner: str, pet_id: str | None = None, species: str | None = None) -> list[dict]:
        return self._list("appointments", owner, self._scope(owner, pet_id, species), "date")

    def update_appointment(self, owner: str, appointment_id: str, status: str | None, day: str | None,
                           time: str | None, notes: str | None) -> dict:
        if status and status not in care.APPOINTMENT_STATUSES:
            raise ValueError(f"Estado desconocido. Opciones: {', '.join(care.APPOINTMENT_STATUSES)}")
        return self._update("appointments", owner, appointment_id,
                            {"status": status, "date": _iso(day), "time": time, "notes": notes})

    def add_reminder(self, owner: str, pet_id: str, title: str, due: str | None, repeat: str | None,
                     notes: str | None, kind: str = "otro", product: str | None = None,
                     last_done: str | None = None) -> dict:
        """`due` wins; otherwise the date follows `repeat` from `last_done`, or today when neither is known."""
        self.require_pet(owner, pet_id)
        if kind not in care.REMINDER_KINDS:
            raise ValueError(f"Tipo de recordatorio desconocido. Opciones: {', '.join(care.REMINDER_KINDS)}")
        following = care.next_due_date(care.parse_date(last_done), repeat or "") if last_done else None
        if repeat:
            care.next_due_date(self.today(), repeat)
        due = due or (following.isoformat() if following else self.today().isoformat())
        return self._insert("reminders", owner, {"pet_id": pet_id, "kind": kind, "title": title, "due": _iso(due),
                                                 "repeat": repeat, "product": product, "notes": notes,
                                                 "completed": False})

    def reminders(self, owner: str, pet_id: str | None = None, include_completed: bool = False,
                  species: str | None = None) -> list[dict]:
        query = {**self._scope(owner, pet_id, species), **({} if include_completed else {"completed": False})}
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
            follow = self.add_reminder(owner, reminder["pet_id"], reminder["title"], nxt.isoformat(),
                                       reminder["repeat"], reminder.get("notes"), reminder.get("kind", "otro"),
                                       reminder.get("product"))
        return {"completed": reminder_id, "title": reminder["title"], "pet_id": reminder["pet_id"],
                "done": done_date.isoformat(), "next": follow}

    def care_plan(self, owner: str, pet_id: str) -> dict:
        """Suggested preventive reminders for the pet's species and age, flagging the kinds already scheduled."""
        pet = self.pet(owner, pet_id)
        species = pet.get("species", care.DEFAULT_SPECIES)
        scheduled = {doc.get("kind") for doc in self.db.reminders.find(
            {"owner": owner, "pet_id": pet_id, "completed": False}, {"kind": 1})}
        suggestions = [{**item, "already_scheduled": item["kind"] in scheduled}
                       for item in care.care_plan(species, pet.get("age_months"), self._size(pet))]
        return {"pet": pet["name"], "age_months": pet.get("age_months"), "suggestions": suggestions,
                "pending_vaccines": [v for v in self.vaccines(owner, pet_id) if v.get("next_due")],
                "note": f"Plan orientativo. Confirma productos y frecuencias con el veterinario del "
                        f"{care.SPECIES[species][0]}."}

    def add_vet(self, owner: str, **fields: object) -> dict:
        if fields.get("primary"):
            self.db.vets.update_many({"owner": owner}, {"$set": {"primary": False}})
        return self._insert("vets", owner, fields)

    def vets(self, owner: str) -> list[dict]:
        return self._list("vets", owner, sort="name")

    def delete_vet(self, owner: str, vet_id: str) -> dict:
        return self._delete("vets", owner, vet_id)

    # --- agenda and summaries --------------------------------------------------------------------

    def agenda(self, owner: str, days: int | None = 30, pet_id: str | None = None,
               species: str | None = None) -> list[dict]:
        """Overdue and upcoming vaccines, appointments and reminders, oldest first. Without a species it covers
        every pet, which is what the shared calendar feed needs."""
        today = self.today()
        horizon = (today + timedelta(days=days)).isoformat() if days is not None else "9999-12-31"
        names = {pet["_id"]: pet["name"] for pet in self.db.pets.find({"owner": owner}, {"name": 1})}
        base = {"owner": owner, **self._scope(owner, pet_id, species)}
        items = [
            *({"kind": "vacuna", "id": doc["_id"], "pet_id": doc["pet_id"], "date": doc["next_due"],
               "title": f"Vacuna {doc.get('next_dose') or doc['name']}", "detail": doc.get("veterinarian")}
              for doc in self.db.vaccines.find({**base, "next_due": {"$ne": None, "$lte": horizon}})),
            *({"kind": "cita", "id": doc["_id"], "pet_id": doc["pet_id"], "date": doc["date"],
               "time": doc.get("time"), "title": f"Cita: {doc['reason']}",
               "detail": ", ".join(filter(None, (doc.get("veterinarian"), doc.get("clinic"))))}
              for doc in self.db.appointments.find({**base, "status": {"$in": ["programada", "confirmada"]},
                                                    "date": {"$lte": horizon}})),
            *({"kind": doc.get("kind", "otro"), "id": doc["_id"], "pet_id": doc["pet_id"], "date": doc["due"],
               "title": doc["title"], "detail": ", ".join(filter(None, (doc.get("product"), doc.get("notes"))))}
              for doc in self.db.reminders.find({**base, "completed": False, "due": {"$lte": horizon}})),
        ]
        for item in items:
            item["pet"] = names.get(item["pet_id"], "")
            item["overdue"] = item["date"] < today.isoformat()
        return sorted(items, key=lambda item: (item["date"], item.get("time") or ""))

    def health_summary(self, owner: str, pet_id: str) -> dict:
        pet = self.pet(owner, pet_id)
        today = self.today().isoformat()
        records = self.records(owner, pet_id)
        weights = self.weights(owner, pet_id)
        medications = [
            {**med, "record_date": record["date"]}
            for record in records for med in record.get("medications", [])
            if med.get("active", True) and (not med.get("end_date") or _iso(med["end_date"]) >= today)
        ]
        agenda = self.agenda(owner, None, pet_id)
        return {
            "pet": pet,
            "total_visits": len(records),
            "last_visit": records[0] if records else None,
            "current_weight_kg": weights[-1]["weight_kg"] if weights else pet.get("weight_kg"),
            "weight_trend": [{"date": w["date"], "weight_kg": w["weight_kg"]} for w in weights[-6:]],
            "active_conditions": [c for c in self.conditions(owner, pet_id) if c.get("active")],
            "active_medications": medications,
            "overdue": [item for item in agenda if item["overdue"]],
            "upcoming": [item for item in agenda if not item["overdue"]][:10],
        }

    # --- sharing ---------------------------------------------------------------------------------

    def share_token(self, owner: str, pet_id: str, rotate: bool = False) -> str:
        pet = self.require_pet(owner, pet_id)
        if pet.get("share_token") and not rotate:
            return pet["share_token"]
        token = secrets.token_urlsafe(16)
        self.db.pets.update_one({"_id": pet_id, "owner": owner}, {"$set": {"share_token": token}})
        return token

    def stop_sharing(self, owner: str, pet_id: str) -> dict:
        self.require_pet(owner, pet_id)
        self.db.pets.update_one({"_id": pet_id, "owner": owner}, {"$unset": {"share_token": ""}})
        return {"pet_id": pet_id, "shared": False}

    def public_card(self, token: str) -> dict | None:
        """The read-only carné a share token unlocks: the pet profile and its vaccines, nothing clinical."""
        pet = self.db.pets.find_one({"share_token": token})
        if pet is None:
            return None
        owner = pet["owner"]
        vaccines = self._list("vaccines", owner, {"pet_id": pet["_id"]}, "next_due")
        public = {key: value for key, value in _public(pet).items() if key not in ("share_token", "notes")}
        has_photo = self.db.photos.count_documents({"pet_id": pet["_id"], "owner": owner}) > 0
        return {"pet": {**public, **self._profile(public), "has_photo": has_photo}, "vaccines": vaccines,
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

    def photo_upload_token(self, owner: str, pet_id: str) -> str:
        self.require_pet(owner, pet_id)
        token = secrets.token_urlsafe(16)
        self.db.uploads.insert_one({"_id": token, "owner": owner, "pet_id": pet_id,
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
        pet = self.db.pets.find_one({"_id": upload["pet_id"], "owner": upload["owner"]}, {"name": 1})
        return {"owner": upload["owner"], "pet_id": upload["pet_id"], "name": pet["name"]} if pet else None

    def save_photo(self, token: str, data: bytes, content_type: str) -> dict:
        target = self.upload_target(token)
        if target is None:
            raise NotFound("El enlace para subir la foto venció. Pide uno nuevo en el chat.")
        if not content_type.startswith("image/"):
            raise ValueError("El archivo debe ser una imagen.")
        if len(data) > MAX_PHOTO_BYTES:
            raise ValueError("La foto supera 5 MB.")
        self.db.photos.replace_one({"_id": target["pet_id"]}, {
            "_id": target["pet_id"], "owner": target["owner"], "pet_id": target["pet_id"],
            "content_type": content_type, "data": data, "updated_at": _now()}, upsert=True)
        self.db.uploads.delete_one({"_id": token})
        return target

    def photo(self, pet_id: str) -> dict | None:
        return self.db.photos.find_one({"_id": pet_id})
