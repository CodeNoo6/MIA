"""Households: several MIA users caring for the same cats.

Every Cat Life document carries an `owner`, the data space it belongs to. A user outside any household owns
the space named after their own MIA user id; a household member works in the household's space instead.
Joining moves the user's own cats into the household when they ask for it; the last member to leave takes
the household's cats back to their personal space, so nothing is orphaned.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from pymongo import DESCENDING
from pymongo.database import Database

OWNED = ("cats", "vaccines", "records", "weights", "conditions", "appointments", "reminders", "vets", "photos",
         "activity")
INVITE_TTL = timedelta(days=7)
EMAIL_INVITE_TTL = timedelta(days=14)
ACTIVITY_TTL = timedelta(days=180)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _drop_none(doc: dict) -> dict:
    return {key: value for key, value in doc.items() if value is not None}


class Family:
    def __init__(self, db: Database):
        self.db = db

    def ensure_indexes(self) -> None:
        self.db.members.create_index("household")
        self.db.invites.create_index("email", sparse=True)
        self.db.invites.create_index("expires_at", expireAfterSeconds=0)
        self.db.activity.create_index([("owner", 1), ("at", DESCENDING)])
        self.db.activity.create_index("at", expireAfterSeconds=int(ACTIVITY_TTL.total_seconds()))

    def space(self, user_id: str, name: str | None = None, email: str | None = None) -> str:
        """The data space this MIA user works in, refreshing the name and email other members see."""
        member = self.db.members.find_one({"_id": user_id})
        if member is None:
            return user_id
        fresh = _drop_none({"name": name, "email": email.lower() if email else None})
        if any(member.get(key) != value for key, value in fresh.items()):
            self.db.members.update_one({"_id": user_id}, {"$set": fresh})
        return member["household"]

    def _move(self, source: str, target: str) -> dict:
        moved = {name: self.db[name].update_many({"owner": source}, {"$set": {"owner": target}}).modified_count
                 for name in OWNED}
        return {name: count for name, count in moved.items() if count}

    def status(self, user_id: str) -> dict:
        member = self.db.members.find_one({"_id": user_id})
        if member is None:
            return {"in_family": False}
        members = self.db.members.find({"household": member["household"]}).sort("joined_at", 1)
        return {
            "in_family": True,
            "your_role": member["role"],
            "members": [{"user_id": m["_id"], "name": m.get("name") or "Sin nombre", "role": m["role"],
                         "joined": _aware(m["joined_at"]).date().isoformat(), "is_you": m["_id"] == user_id}
                        for m in members],
        }

    def _household(self, user_id: str, name: str | None) -> str:
        """The user's household, creating it from their own space (and cats) on first share."""
        member = self.db.members.find_one({"_id": user_id})
        if member is not None:
            return member["household"]
        household = f"hogar-{secrets.token_hex(6)}"
        self.db.members.insert_one({"_id": user_id, "household": household, "name": name, "role": "admin",
                                    "joined_at": _now()})
        self._move(user_id, household)
        return household

    def _new_invite(self, household: str, user_id: str, name: str | None, ttl: timedelta,
                    email: str | None = None) -> dict:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        expires = _now() + ttl
        self.db.invites.insert_one(_drop_none({"_id": code, "household": household, "created_by": user_id,
                                               "inviter": name, "email": email, "expires_at": expires}))
        return {"code": code, "expires": expires.date().isoformat()}

    def invite(self, user_id: str, name: str | None) -> dict:
        """A reusable 8-character code valid for 7 days for anyone the user hands it to."""
        return self._new_invite(self._household(user_id, name), user_id, name, INVITE_TTL)

    def invite_email(self, user_id: str, name: str | None, own_email: str | None, email: str) -> dict:
        """A personal invitation for one MIA account. Only a user signed in with that email can accept it."""
        email = email.strip().lower()
        if "@" not in email:
            raise ValueError("Escribe un correo válido.")
        if own_email and email == own_email.lower():
            raise ValueError("Ese es tu propio correo.")
        household = self._household(user_id, name)
        if self.db.members.find_one({"household": household, "email": email}):
            raise ValueError("Esa persona ya está en tu hogar.")
        self.db.invites.delete_many({"household": household, "email": email})
        return {**self._new_invite(household, user_id, name, EMAIL_INVITE_TTL, email), "email": email}

    def pending(self, email: str | None) -> list[dict]:
        if not email:
            return []
        invites = self.db.invites.find({"email": email.lower(), "expires_at": {"$gt": _now()}})
        return [{"code": invite["_id"], "from": invite.get("inviter") or "Un usuario de MIA",
                 "members": [m.get("name") or "Sin nombre" for m in self.db.members.find({"household": invite["household"]})],
                 "cats": [c["name"] for c in self.db.cats.find({"owner": invite["household"]}, {"name": 1})],
                 "expires": _aware(invite["expires_at"]).date().isoformat()} for invite in invites]

    def decline(self, email: str | None, code: str) -> dict:
        removed = self.db.invites.delete_one({"_id": code.strip().upper(), "email": (email or "").lower()})
        if removed.deleted_count == 0:
            raise ValueError("No tienes una invitación con ese código.")
        return {"declined": code}

    def join(self, user_id: str, name: str | None, code: str, bring_my_cats: bool, email: str | None = None) -> dict:
        invite = self.db.invites.find_one({"_id": code.strip().upper()})
        if invite is None or _aware(invite["expires_at"]) < _now():
            raise ValueError("El código no existe o venció. Pide uno nuevo a quien te invitó.")
        if invite.get("email") and invite["email"] != (email or "").lower():
            raise PermissionError("Esta invitación es para otra cuenta de MIA.")
        current = self.db.members.find_one({"_id": user_id})
        if current and current["household"] == invite["household"]:
            return {"joined": True, "already_member": True}
        if current:
            raise ValueError("Ya perteneces a otro hogar. Sal de él primero con leave_family.")
        self.db.members.insert_one(_drop_none({"_id": user_id, "household": invite["household"], "name": name,
                                               "email": (email or "").lower() or None, "role": "miembro",
                                               "joined_at": _now()}))
        if invite.get("email"):
            self.db.invites.delete_one({"_id": invite["_id"]})
        moved = self._move(user_id, invite["household"]) if bring_my_cats else {}
        return {"joined": True, "moved": moved, "kept_private": not bring_my_cats}

    def leave(self, user_id: str) -> dict:
        member = self.db.members.find_one({"_id": user_id})
        if member is None:
            raise ValueError("No perteneces a ningún hogar.")
        household = member["household"]
        self.db.members.delete_one({"_id": user_id})
        remaining = list(self.db.members.find({"household": household}).sort("joined_at", 1))
        if not remaining:
            self.db.invites.delete_many({"household": household})
            return {"left": True, "took_cats": self._move(household, user_id)}
        if member["role"] == "admin" and not any(m["role"] == "admin" for m in remaining):
            self.db.members.update_one({"_id": remaining[0]["_id"]}, {"$set": {"role": "admin"}})
        return {"left": True, "cats_stay_with_family": True}

    def remove(self, admin_id: str, member_id: str) -> dict:
        admin = self.db.members.find_one({"_id": admin_id})
        if admin is None or admin["role"] != "admin":
            raise PermissionError("Solo quien administra el hogar puede sacar a alguien.")
        if member_id == admin_id:
            raise ValueError("Para salir tú, usa leave_family.")
        removed = self.db.members.delete_one({"_id": member_id, "household": admin["household"]})
        if removed.deleted_count == 0:
            raise ValueError("Esa persona no está en tu hogar.")
        return {"removed": member_id}

    def log(self, space: str, user_id: str, name: str | None, action: str, cat_id: str | None,
            detail: str | None) -> None:
        self.db.activity.insert_one({"owner": space, "by": user_id, "by_name": name, "action": action,
                                     "cat_id": cat_id, "detail": detail, "at": _now()})

    def activity(self, space: str, user_id: str, days: int = 7) -> list[dict]:
        since = _now() - timedelta(days=days)
        names = {cat["_id"]: cat["name"] for cat in self.db.cats.find({"owner": space}, {"name": 1})}
        return [
            {"when": _aware(entry["at"]).isoformat(timespec="minutes"), "who": entry.get("by_name") or "Alguien",
             "is_you": entry["by"] == user_id, "action": entry["action"], "detail": entry.get("detail"),
             "cat": names.get(entry.get("cat_id"))}
            for entry in self.db.activity.find({"owner": space, "at": {"$gte": since}}).sort("at", -1).limit(50)
        ]
