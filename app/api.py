from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Path, Request, Response, status
from pymongo.database import Database

from app import db as database
from app.models import CampaignCreate, CampaignDocument, JobAccepted, JobDocument


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = database.connect()
    client.admin.command("ping")
    mongo = client[os.getenv("MONGODB_DATABASE", "creator_ranker")]
    database.init_db(mongo)
    app.state.mongo_client = client
    app.state.mongo = mongo
    try:
        yield
    finally:
        client.close()


app = FastAPI(title="Oskar Kuban Creator Ranking API", version="1.0.0", lifespan=lifespan)


def _mongo(request: Request) -> Database:
    return request.app.state.mongo


@app.get("/health")
def health(request: Request) -> dict[str, str]:
    try:
        request.app.state.mongo.command("ping")
    except Exception as error:
        raise HTTPException(status_code=503, detail="database_unavailable") from error
    return {"status": "ok"}


@app.put("/campaigns/{campaign_id}", response_model=CampaignDocument, status_code=status.HTTP_200_OK)
def put_campaign(
    campaign: CampaignCreate,
    request: Request,
    campaign_id: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$"),
) -> Any:
    mongo = _mongo(request)
    definition = campaign.model_dump(mode="json")
    definition["platform"] = "instagram"
    try:
        document = database.upsert_campaign(mongo, campaign_id, definition)
    except ValueError as error:
        raise HTTPException(status_code=409, detail="campaign_id_conflict") from error
    return CampaignDocument.model_validate(database.get_campaign(mongo, document["_id"]))


@app.get("/campaigns/{campaign_id}", response_model=CampaignDocument)
def read_campaign(
    request: Request,
    campaign_id: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$"),
) -> CampaignDocument:
    document = database.get_campaign(_mongo(request), campaign_id)
    if document is None:
        raise HTTPException(status_code=404, detail="campaign_not_found")
    return CampaignDocument.model_validate(document)


@app.post(
    "/campaigns/{campaign_id}/jobs",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_campaign_job(
    request: Request,
    response: Response,
    campaign_id: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
) -> JobAccepted:
    mongo = _mongo(request)
    if mongo.campaigns.find_one({"_id": campaign_id}, {"_id": 1}) is None:
        raise HTTPException(status_code=404, detail="campaign_not_found")
    job = database.create_job(mongo, campaign_id, idempotency_key)
    response.headers["Location"] = f"/jobs/{job['_id']}"
    return JobAccepted(job_id=job["_id"], status=job["status"])


@app.get("/jobs/{job_id}", response_model=JobDocument)
def read_job(
    request: Request,
    job_id: str = Path(pattern=r"^[a-f0-9]{32}$"),
) -> JobDocument:
    job = database.get_job(_mongo(request), job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return JobDocument.model_validate(job)
