"""Environment settings shared by the portal and the MCP server, and the Mongo-backed store they use."""

from __future__ import annotations

import os
from functools import lru_cache

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from catlife.family import Family
from catlife.store import Store

PUBLIC_URL = os.environ.get("CATLIFE_PUBLIC_URL", "http://localhost:8200").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://mongodb:27017")
DATABASE = os.environ.get("CATLIFE_DB", "catlife")
MCP_TOKEN = os.environ.get("CATLIFE_MCP_TOKEN", "")
PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")
MIA_URL = os.environ.get("MIA_URL", "http://localhost:3080").rstrip("/")
MIA_USERS_DB = os.environ.get("MIA_USERS_DB", "")
MIA_USERS_MONGO_URL = os.environ.get("MIA_USERS_MONGO_URL", "") or MONGO_URL


@lru_cache(maxsize=1)
def database() -> Database:
    return MongoClient(MONGO_URL, tz_aware=True)[DATABASE]


@lru_cache(maxsize=1)
def store() -> Store:
    instance = Store(database())
    instance.ensure_indexes()
    return instance


@lru_cache(maxsize=1)
def family() -> Family:
    instance = Family(database())
    instance.ensure_indexes()
    return instance


def card_url(token: str) -> str:
    return f"{PUBLIC_URL}/carne/{token}"


@lru_cache(maxsize=1)
def _mia_users() -> Collection:
    return MongoClient(MIA_USERS_MONGO_URL, serverSelectionTimeoutMS=5000)[MIA_USERS_DB].users


def mia_user_exists(email: str) -> bool | None:
    """Read-only lookup in LibreChat's users collection; None when the directory is not configured."""
    if not MIA_USERS_DB:
        return None
    return _mia_users().count_documents({"email": email.strip().lower()}, limit=1) > 0
