from __future__ import annotations

import logging
import os
import time
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

from apify_client import ApifyClient
from pymongo.database import Database

from app import apify, db as database


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


def process_job(
    mongo: Database,
    job: dict[str, Any],
    worker_id: str,
    client: ApifyClient | None,
) -> None:
    job_id = job["_id"]
    campaign_id = job["campaign_id"]
    campaign = mongo.campaigns.find_one({"_id": campaign_id})
    if campaign is None:
        database.finish_job(mongo, job_id, worker_id, "failed", "campaign_not_found")
        return
    if client is None:
        database.finish_job(mongo, job_id, worker_id, "failed", "apify_token_missing")
        return

    def record_run(run_record: dict[str, Any]) -> None:
        database.record_actor_run(mongo, job_id, worker_id, run_record)
        logging.info("job=%s actor=%s run=%s", job_id, run_record["actor_id"], run_record["run_id"])

    try:
        definition = campaign["definition"]
        start = date.fromisoformat(definition["period_start"])
        end = date.fromisoformat(definition["period_end"])
        max_cost = Decimal(os.getenv("APIFY_MAX_RUN_COST_USD", "0.50"))
        posts = apify.run_posts_actor(
            client,
            definition["creator_usernames"],
            definition["post_urls"],
            start,
            end,
            definition["results_limit_per_creator"],
            max_cost,
            record_run,
        )

        existing_creators = campaign.get("creators", [])
        usernames = {
            creator["username"]
            for creator in existing_creators
            if creator.get("username")
        }
        usernames.update(post["username"] for post in posts)
        profile_rows = apify.run_profiles_actor(client, sorted(usernames), max_cost, record_run)
        profile_by_username = {profile["username"]: profile for profile in profile_rows}
        existing_by_username = {
            creator["username"]: creator
            for creator in existing_creators
            if creator.get("username")
        }
        creators = []
        for username in sorted(usernames):
            creator = {**existing_by_username.get(username, {}), **profile_by_username.get(username, {})}
            creator["username"] = username
            creators.append(creator)

        database.save_campaign_result(mongo, campaign_id, creators, posts)
        database.finish_job(mongo, job_id, worker_id, "done")
        logging.info("job=%s status=done posts=%s", job_id, len(posts))
    except Exception as error:
        error_code = "apify_run_failed" if "actor_run" in str(error) else "processing_failed"
        database.finish_job(mongo, job_id, worker_id, "failed", error_code)
        logging.error("job=%s status=failed code=%s", job_id, error_code)


def main() -> None:
    mongo_client = database.connect()
    mongo = mongo_client[os.getenv("MONGODB_DATABASE", "creator_ranker")]
    database.init_db(mongo)
    token = os.getenv("APIFY_TOKEN")
    apify_client = ApifyClient(token) if token else None
    worker_id = os.getenv("HOSTNAME") or uuid4().hex
    poll_seconds = max(1.0, float(os.getenv("WORKER_POLL_SECONDS", "2")))

    logging.info("worker started id=%s", worker_id)
    try:
        while True:
            job = database.claim_job(mongo, worker_id)
            if job is None:
                time.sleep(poll_seconds)
                continue
            logging.info("job=%s status=running", job["_id"])
            process_job(mongo, job, worker_id, apify_client)
    finally:
        mongo_client.close()


if __name__ == "__main__":
    main()
