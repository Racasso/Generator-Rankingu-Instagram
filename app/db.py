from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, MongoClient, ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError


def connect() -> MongoClient:
    return MongoClient(
        os.getenv("MONGODB_URI", "mongodb://localhost:27017"),
        serverSelectionTimeoutMS=5_000,
    )


def init_db(db: Database) -> None:
    db.campaigns.create_index([("type", ASCENDING), ("_id", ASCENDING)], unique=True)
    db.jobs.create_index([("status", ASCENDING), ("created_at", ASCENDING)])
    db.jobs.create_index(
        [("campaign_id", ASCENDING), ("idempotency_key", ASCENDING)],
        unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
    )


def upsert_campaign(db: Database, campaign_id: str, definition: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    initial_creators = [
        {"username": username, "followers_count": None, "followers_observed_at": None}
        for username in definition["creator_usernames"]
    ]
    db.campaigns.update_one(
        {"_id": campaign_id},
        {
            "$setOnInsert": {
                "_id": campaign_id,
                "type": "campaign",
                "schema_version": 1,
                "created_at": now,
                "updated_at": now,
                "definition": definition,
                "creators": initial_creators,
                "posts": [],
            }
        },
        upsert=True,
    )
    document = db.campaigns.find_one({"_id": campaign_id})
    if document["definition"] != definition:
        raise ValueError("campaign_id_conflict")
    return document


def create_job(db: Database, campaign_id: str, idempotency_key: str | None) -> dict[str, Any]:
    if idempotency_key:
        existing = db.jobs.find_one({"campaign_id": campaign_id, "idempotency_key": idempotency_key})
        if existing:
            return existing

    now = datetime.now(timezone.utc)
    job = {
        "_id": uuid4().hex,
        "type": "job",
        "schema_version": 1,
        "created_at": now,
        "updated_at": now,
        "campaign_id": campaign_id,
        "status": "queued",
        "attempts": 0,
        "cost_total_usd": 0.0,
        "actor_runs": [],
        "error_code": None,
    }
    if idempotency_key:
        job["idempotency_key"] = idempotency_key
    try:
        db.jobs.insert_one(job)
    except DuplicateKeyError:
        return db.jobs.find_one({"campaign_id": campaign_id, "idempotency_key": idempotency_key})
    return job


def get_job(db: Database, job_id: str) -> dict[str, Any] | None:
    return db.jobs.find_one({"_id": job_id})


def claim_job(db: Database, worker_id: str, lease_seconds: int = 3_600) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    return db.jobs.find_one_and_update(
        {
            "$or": [
                {"status": "queued"},
                {"status": "running", "lease_expires_at": {"$lt": now}},
            ]
        },
        {
            "$set": {
                "status": "running",
                "worker_id": worker_id,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
                "updated_at": now,
            },
            "$inc": {"attempts": 1},
        },
        sort=[("created_at", ASCENDING)],
        return_document=ReturnDocument.AFTER,
    )


def record_actor_run(db: Database, job_id: str, worker_id: str, run: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    update: dict[str, Any] = {
        "$push": {"actor_runs": run},
        "$set": {"updated_at": now},
    }
    if run.get("cost_usd") is not None:
        update["$inc"] = {"cost_total_usd": run["cost_usd"]}
    db.jobs.update_one({"_id": job_id, "worker_id": worker_id}, update)


def finish_job(
    db: Database,
    job_id: str,
    worker_id: str,
    status: str,
    error_code: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    db.jobs.update_one(
        {"_id": job_id, "worker_id": worker_id},
        {
            "$set": {
                "status": status,
                "error_code": error_code,
                "finished_at": now,
                "updated_at": now,
            },
            "$unset": {"worker_id": "", "lease_expires_at": ""},
        },
    )


def save_campaign_result(
    db: Database,
    campaign_id: str,
    creators: list[dict[str, Any]],
    posts: list[dict[str, Any]],
) -> None:
    """Merge snapshots atomically; a post URL replaces its previous campaign copy."""
    now = datetime.now(timezone.utc)
    creator_names = [creator["username"] for creator in creators]
    post_urls = [post["url"] for post in posts]

    db.campaigns.update_one(
        {"_id": campaign_id},
        [
            {
                "$set": {
                    "creators": {
                        "$concatArrays": [
                            {
                                "$filter": {
                                    "input": {"$ifNull": ["$creators", []]},
                                    "as": "existing",
                                    "cond": {"$not": [{"$in": ["$$existing.username", {"$literal": creator_names}]}]},
                                }
                            },
                            {"$literal": creators},
                        ]
                    },
                    "posts": {
                        "$concatArrays": [
                            {
                                "$filter": {
                                    "input": {"$ifNull": ["$posts", []]},
                                    "as": "existing",
                                    "cond": {"$not": [{"$in": ["$$existing.url", {"$literal": post_urls}]}]},
                                }
                            },
                            {"$literal": posts},
                        ]
                    },
                    "updated_at": now,
                }
            }
        ],
    )


def _sum_field(posts: str, field: str) -> dict[str, Any]:
    return {
        "$sum": {
            "$map": {
                "input": posts,
                "as": "post",
                "in": {"$ifNull": [f"$$post.{field}", 0]},
            }
        }
    }


def campaign_read_pipeline(campaign_id: str) -> list[dict[str, Any]]:
    creator_posts = {
        "$filter": {
            "input": {"$ifNull": ["$posts", []]},
            "as": "post",
            "cond": {"$eq": ["$$post.username", "$$creator.username"]},
        }
    }
    likes_total = _sum_field("$$creator_posts", "likes")
    comments_total = _sum_field("$$creator_posts", "comments")
    video_plays_total = _sum_field("$$creator_posts", "video_plays")
    video_plays_available_count = {
        "$size": {
            "$filter": {
                "input": "$$creator_posts",
                "as": "post",
                "cond": {"$ne": ["$$post.video_plays", None]},
            }
        }
    }
    complete_interaction_posts = {
        "$size": {
            "$filter": {
                "input": "$$creator_posts",
                "as": "post",
                "cond": {
                    "$and": [
                        {"$ne": ["$$post.likes", None]},
                        {"$ne": ["$$post.comments", None]},
                    ]
                },
            }
        }
    }
    post_count = {"$size": "$$creator_posts"}
    rate_is_measurable = {
        "$and": [
            {"$gt": [{"$ifNull": ["$$creator.followers_count", 0]}, 0]},
            {"$gt": [post_count, 0]},
            {"$eq": [complete_interaction_posts, post_count]},
        ]
    }

    return [
        {"$match": {"_id": campaign_id}},
        {
            "$set": {
                "creators": {
                    "$map": {
                        "input": {"$ifNull": ["$creators", []]},
                        "as": "creator",
                        "in": {
                            "$let": {
                                "vars": {"creator_posts": creator_posts},
                                "in": {
                                    "$mergeObjects": [
                                        "$$creator",
                                        {
                                            "posts": "$$creator_posts",
                                            "metrics": {
                                                "post_count": post_count,
                                                "likes_total": likes_total,
                                                "comments_total": comments_total,
                                                "complete_interaction_posts": complete_interaction_posts,
                                                "actual_reach": None,
                                                "video_plays_total": {
                                                    "$cond": [
                                                        {"$gt": [video_plays_available_count, 0]},
                                                        video_plays_total,
                                                        None,
                                                    ]
                                                },
                                                "engagement_rate_by_followers_pct": {
                                                    "$cond": [
                                                        rate_is_measurable,
                                                        {
                                                            "$round": [
                                                                {
                                                                    "$multiply": [
                                                                        100,
                                                                        {
                                                                            "$divide": [
                                                                                {"$add": [likes_total, comments_total]},
                                                                                {
                                                                                    "$multiply": [
                                                                                        post_count,
                                                                                        "$$creator.followers_count",
                                                                                    ]
                                                                                },
                                                                            ]
                                                                        },
                                                                    ]
                                                                },
                                                                4,
                                                            ]
                                                        },
                                                        None,
                                                    ]
                                                },
                                            },
                                        },
                                    ]
                                },
                            }
                        },
                    }
                }
            }
        },
        {
            "$set": {
                "creators": {
                    "$sortArray": {
                        "input": "$creators",
                        "sortBy": {
                            "metrics.engagement_rate_by_followers_pct": -1,
                            "followers_count": -1,
                            "username": 1,
                        },
                    }
                }
            }
        },
        {
            "$set": {
                "creators": {
                    "$map": {
                        "input": {"$range": [0, {"$size": "$creators"}]},
                        "as": "rank_index",
                        "in": {
                            "$mergeObjects": [
                                {"$arrayElemAt": ["$creators", "$$rank_index"]},
                                {"rank": {"$add": ["$$rank_index", 1]}},
                            ]
                        },
                    }
                }
            }
        },
        {
            "$set": {
                "summary": {
                    "creator_count": {"$size": "$creators"},
                    "post_count": {"$size": {"$ifNull": ["$posts", []]}},
                }
            }
        },
        {"$project": {"posts": 0}},
    ]


def get_campaign(db: Database, campaign_id: str) -> dict[str, Any] | None:
    return next(db.campaigns.aggregate(campaign_read_pipeline(campaign_id)), None)
