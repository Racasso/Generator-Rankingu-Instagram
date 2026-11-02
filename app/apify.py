from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from apify_client import ApifyClient


POSTS_ACTOR_ID = os.getenv("APIFY_POSTS_ACTOR_ID", "apify/instagram-post-scraper")
PROFILE_ACTOR_ID = os.getenv("APIFY_PROFILE_ACTOR_ID", "apify/instagram-profile-scraper")


def _run_actor(
    client: ApifyClient,
    actor_id: str,
    run_input: dict[str, Any],
    max_cost_usd: Decimal,
    on_run: Callable[[dict[str, Any]], None],
) -> list[dict[str, Any]]:
    run = client.actor(actor_id).call(
        run_input=run_input,
        max_total_charge_usd=max_cost_usd,
        run_timeout=timedelta(minutes=20),
    )
    if run is None:
        raise RuntimeError("actor_run_missing")

    status_value = getattr(run.status, "value", run.status)
    status = str(status_value).upper()
    run_record = {
        "actor_id": actor_id,
        "run_id": run.id,
        "status": status,
        "cost_usd": run.usage_total_usd,
    }
    on_run(run_record)
    if not status.endswith("SUCCEEDED"):
        raise RuntimeError("actor_run_failed")

    return list(client.dataset(run.default_dataset_id).iterate_items())


def run_posts_actor(
    client: ApifyClient,
    creator_usernames: list[str],
    post_urls: list[str],
    period_start: date,
    period_end: date,
    results_limit_per_creator: int,
    max_cost_usd: Decimal,
    on_run: Callable[[dict[str, Any]], None],
) -> list[dict[str, Any]]:
    actor_inputs = [*creator_usernames, *post_urls]
    run_input: dict[str, Any] = {
        "username": actor_inputs,
        "skipPinnedPosts": True,
        "dataDetailLevel": "basicData",
    }
    if creator_usernames:
        run_input.update(
            {
                "resultsLimit": results_limit_per_creator,
                "onlyPostsNewerThan": period_start.isoformat(),
            }
        )
    raw_posts = _run_actor(client, POSTS_ACTOR_ID, run_input, max_cost_usd, on_run)
    return normalize_posts(raw_posts, period_start, period_end)


def run_profiles_actor(
    client: ApifyClient,
    usernames: list[str],
    max_cost_usd: Decimal,
    on_run: Callable[[dict[str, Any]], None],
) -> list[dict[str, Any]]:
    if not usernames:
        return []
    raw_profiles = _run_actor(
        client,
        PROFILE_ACTOR_ID,
        {"usernames": usernames, "includeAboutSection": False},
        max_cost_usd,
        on_run,
    )
    return normalize_profiles(raw_profiles)


def normalize_posts(
    raw_posts: list[dict[str, Any]],
    period_start: date,
    period_end: date,
) -> list[dict[str, Any]]:
    observed_at = datetime.now(timezone.utc)
    posts_by_url: dict[str, dict[str, Any]] = {}

    for raw in raw_posts:
        url = raw.get("url")
        username = raw.get("ownerUsername")
        if not url or not username:
            continue

        published_at = _parse_timestamp(raw.get("timestamp"))
        if published_at is None or not period_start <= published_at.date() <= period_end:
            continue

        likes = _nonnegative_int(raw.get("likesCount"))
        comments = _nonnegative_int(raw.get("commentsCount"))
        posts_by_url[url] = {
            "url": url,
            "apify_id": str(raw["id"]) if raw.get("id") is not None else None,
            "username": username.lower(),
            "media_type": raw.get("type"),
            "published_at": published_at,
            "likes": likes,
            "comments": comments,
            "video_plays": _nonnegative_int(raw.get("videoPlayCount")),
            "video_views": _nonnegative_int(raw.get("videoViewCount")),
            "observed_at": observed_at,
        }

    return list(posts_by_url.values())


def normalize_profiles(raw_profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observed_at = datetime.now(timezone.utc)
    profiles_by_username: dict[str, dict[str, Any]] = {}
    for raw in raw_profiles:
        username = raw.get("username")
        followers_count = _nonnegative_int(raw.get("followersCount"))
        if username and followers_count is not None:
            profiles_by_username[username.lower()] = {
                "username": username.lower(),
                "followers_count": followers_count,
                "followers_observed_at": observed_at,
            }
    return list(profiles_by_username.values())


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _nonnegative_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None
