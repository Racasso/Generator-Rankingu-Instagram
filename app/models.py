from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    period_start: date
    period_end: date
    creator_usernames: list[str] = Field(default_factory=list, max_length=100)
    post_urls: list[str] = Field(default_factory=list, max_length=200)
    results_limit_per_creator: int = Field(default=50, ge=1, le=100)

    @field_validator("creator_usernames")
    @classmethod
    def normalize_usernames(cls, usernames: list[str]) -> list[str]:
        normalized = [username.strip().removeprefix("@").lower() for username in usernames]
        if any(not username for username in normalized):
            raise ValueError("Creator usernames cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Creator usernames must be unique")
        return normalized

    @field_validator("post_urls")
    @classmethod
    def validate_post_urls(cls, urls: list[str]) -> list[str]:
        normalized = [url.strip() for url in urls]
        for url in normalized:
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in {"instagram.com", "www.instagram.com"}:
                raise ValueError("Post URLs must be HTTPS Instagram URLs")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Post URLs must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_period_and_sources(self) -> CampaignCreate:
        if self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        if bool(self.creator_usernames) == bool(self.post_urls):
            raise ValueError("Provide creator_usernames or post_urls")
        return self


class CampaignDefinition(CampaignCreate):
    platform: Literal["instagram"] = "instagram"


class CreatorMetrics(BaseModel):
    post_count: int
    likes_total: int
    comments_total: int
    complete_interaction_posts: int
    actual_reach: int | None = None
    video_plays_total: int | None = None
    engagement_rate_by_followers_pct: float | None = None


class PostDocument(BaseModel):
    url: str
    apify_id: str | None = None
    username: str
    media_type: str | None = None
    published_at: datetime | None = None
    likes: int | None = None
    comments: int | None = None
    video_plays: int | None = None
    video_views: int | None = None
    observed_at: datetime


class CreatorDocument(BaseModel):
    rank: int
    username: str
    followers_count: int | None = None
    followers_observed_at: datetime | None = None
    posts: list[PostDocument] = Field(default_factory=list)
    metrics: CreatorMetrics


class CampaignSummary(BaseModel):
    creator_count: int
    post_count: int


class CampaignDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    type: Literal["campaign"] = "campaign"
    schema_version: int = 1
    created_at: datetime
    updated_at: datetime
    definition: CampaignDefinition
    creators: list[CreatorDocument]
    summary: CampaignSummary


class ActorRunRecord(BaseModel):
    actor_id: str
    run_id: str
    status: str
    cost_usd: float | None = None


class JobDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    type: Literal["job"] = "job"
    schema_version: int = 1
    created_at: datetime
    updated_at: datetime
    campaign_id: str
    status: Literal["queued", "running", "done", "failed"]
    attempts: int = 0
    idempotency_key: str | None = None
    cost_total_usd: float = 0.0
    actor_runs: list[ActorRunRecord] = Field(default_factory=list)
    error_code: str | None = None


class JobAccepted(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "failed"]
