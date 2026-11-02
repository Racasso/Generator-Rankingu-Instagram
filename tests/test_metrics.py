from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pymongo.database import Database

from app.apify import normalize_posts, normalize_profiles
from app.db import get_campaign, save_campaign_result, upsert_campaign


FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_actor_fixtures_and_campaign_metrics(mongo: Database) -> None:
    raw_post = read_fixture("apify_instagram_post_sample.json")
    live_post = normalize_posts(raw_post, date(2026, 11, 1), date(2026, 11, 2))[0]
    assert live_post["username"] == "natgeo"
    assert live_post["likes"] == 42_935
    assert live_post["comments"] == 151
    assert live_post["video_plays"] is None

    detailed_post = normalize_posts(
        read_fixture("apify_instagram_post_detailed_docs_sample.json"),
        date(2025, 8, 1),
        date(2025, 8, 31),
    )[0]
    assert detailed_post["video_plays"] == 2_412_253

    raw_profile = read_fixture("apify_instagram_profile_sample.json")
    normalized_profile = normalize_profiles(raw_profile)
    assert normalized_profile[0]["username"] == "natgeo"
    assert normalized_profile[0]["followers_count"] == 268_214_611

    case = read_fixture("metrics_case.json")
    campaign_id = "metrics-fixture"
    definition = {
        "name": "Metrics fixture",
        "platform": "instagram",
        "period_start": "2025-08-01",
        "period_end": "2025-08-31",
        "creator_usernames": [case["creator"]["username"], case["other_creator"]["username"]],
        "post_urls": [],
        "results_limit_per_creator": 50,
    }
    upsert_campaign(mongo, campaign_id, definition)
    observed_at = datetime.now(timezone.utc)
    creators = [
        {**profile, "followers_observed_at": observed_at}
        for profile in [case["creator"], case["other_creator"]]
    ]
    posts = [
        {
            **post,
            "published_at": datetime(2025, 8, 10, tzinfo=timezone.utc),
            "observed_at": observed_at,
        }
        for post in [*case["posts"], case["other_post"]]
    ]
    save_campaign_result(mongo, campaign_id, creators, posts)

    result = get_campaign(mongo, campaign_id)
    metrics = result["creators"][0]["metrics"]
    assert result["creators"][0]["username"] == case["creator"]["username"]
    assert result["creators"][0]["rank"] == 1
    assert result["creators"][1]["username"] == case["other_creator"]["username"]
    assert result["creators"][1]["rank"] == 2
    assert result["creators"][1]["metrics"]["engagement_rate_by_followers_pct"] == 0.01
    for field, expected in case["expected"].items():
        assert metrics[field] == expected
    assert metrics["actual_reach"] is None
    assert result["summary"] == {"creator_count": 2, "post_count": 3}
