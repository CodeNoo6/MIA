"""Environment settings for the habits MCP server and the Mongo-backed store it uses."""

from __future__ import annotations

import os
from functools import lru_cache

from pymongo import MongoClient

from habits.store import Store

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://mongodb:27017")
DATABASE = os.environ.get("HABITS_DB", "habits")
MCP_TOKEN = os.environ.get("HABITS_MCP_TOKEN", "")
DEFAULT_TIMEZONE = os.environ.get("HABITS_TIMEZONE", "America/Bogota")


@lru_cache(maxsize=1)
def store() -> Store:
    instance = Store(MongoClient(MONGO_URL, tz_aware=True)[DATABASE], DEFAULT_TIMEZONE)
    instance.ensure_indexes()
    return instance
