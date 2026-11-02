from __future__ import annotations

import os
from uuid import uuid4

import pytest
from pymongo import MongoClient
from pymongo.database import Database

from app.db import init_db


@pytest.fixture
def mongo() -> Database:
    client = MongoClient(
        os.getenv(
            "TEST_MONGODB_URI",
            os.getenv("MONGODB_URI", "mongodb://localhost:27017"),
        ),
        serverSelectionTimeoutMS=1_000,
    )
    try:
        client.admin.command("ping")
    except Exception:
        client.close()
        pytest.skip("MongoDB is unavailable; start it with docker compose up -d mongo")

    db = client[f"creator_ranker_test_{uuid4().hex}"]
    init_db(db)
    yield db
    client.drop_database(db.name)
    client.close()
