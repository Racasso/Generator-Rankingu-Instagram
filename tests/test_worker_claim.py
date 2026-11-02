from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pymongo.database import Database

from app.db import claim_job, create_job


def test_concurrent_workers_claim_different_jobs(mongo: Database) -> None:
    campaign_id = "worker-claim-fixture"
    jobs = [create_job(mongo, campaign_id, f"request-{index}") for index in range(3)]
    expected_ids = {job["_id"] for job in jobs}

    with ThreadPoolExecutor(max_workers=3) as workers:
        claimed = list(workers.map(lambda index: claim_job(mongo, f"worker-{index}"), range(3)))

    claimed_ids = {job["_id"] for job in claimed if job is not None}
    assert claimed_ids == expected_ids
