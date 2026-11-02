from __future__ import annotations

from datetime import datetime, timezone

from pymongo.database import Database

from app.db import get_campaign, save_campaign_result, upsert_campaign


def test_replaying_campaign_result_replaces_post_by_url(mongo: Database) -> None:
    campaign_id = "idempotency-fixture"
    upsert_campaign(
        mongo,
        campaign_id,
        {
            "name": "Idempotency fixture",
            "platform": "instagram",
            "period_start": "2025-08-01",
            "period_end": "2025-08-31",
            "creator_usernames": ["test_creator"],
            "post_urls": [],
            "results_limit_per_creator": 50,
        },
    )
    observed_at = datetime.now(timezone.utc)
    creator = {"username": "test_creator", "followers_count": 10_000}
    first = {
        "url": "https://www.instagram.com/p/idempotent/",
        "username": "test_creator",
        "media_type": "Image",
        "likes": 10,
        "comments": 1,
        "video_plays": None,
        "published_at": datetime(2025, 8, 10, tzinfo=timezone.utc),
        "observed_at": observed_at,
    }
    replay = {**first, "likes": 12, "observed_at": datetime.now(timezone.utc)}

    save_campaign_result(mongo, campaign_id, [creator], [first])
    save_campaign_result(mongo, campaign_id, [creator], [replay])

    stored = mongo.campaigns.find_one({"_id": campaign_id})
    result = get_campaign(mongo, campaign_id)
    assert len(stored["posts"]) == 1
    assert stored["posts"][0]["likes"] == 12
    assert result["creators"][0]["metrics"]["likes_total"] == 12
