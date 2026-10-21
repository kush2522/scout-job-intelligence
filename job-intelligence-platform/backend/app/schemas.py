from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl, ConfigDict
from typing import Any, Literal

SourceKind = Literal["greenhouse", "lever", "ashby", "smartrecruiters", "adzuna", "jsonld", "career_page"]
class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=250)
    kind: SourceKind
    base_url: HttpUrl
    config_json: dict[str, Any] = Field(default_factory=dict)
    company_name: str | None = Field(default=None, max_length=250)
    website_url: HttpUrl | None = None
    terms_reviewed: bool = False
    terms_review_url: HttpUrl | None = None
    enabled: bool = True
    min_interval_seconds: int = Field(default=2, ge=1, le=3600)
class SourceOut(BaseModel):
    id: int; name: str; kind: str; base_url: str; enabled: bool; terms_reviewed: bool = False
    terms_review_url: str | None = None
    last_run_at: datetime | None = None; last_status: str | None = None
    created_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)
class JobOut(BaseModel):
    id: int; title: str; company_name: str; location: str | None = None
    employment_type: str | None = None; description: str | None = None
    salary_min: float | None = None; salary_max: float | None = None; salary_currency: str | None = None
    skills: list[str] = Field(default_factory=list)
    apply_url: str; canonical_url: str; remote: bool = False
    posted_at: datetime | None = None; first_seen_at: datetime | None = None; last_seen_at: datetime | None = None
    active: bool = True; source_count: int = 1
class CompanyOut(BaseModel):
    id: int; name: str; website_url: str | None = None; careers_url: str | None = None
    industry: str | None = None; country_code: str | None = None
    active_job_count: int = 0
class SourceRunOut(BaseModel):
    id: int; source_id: int | None; source_name: str; trigger: str; status: str
    started_at: datetime; finished_at: datetime | None; jobs_seen: int; jobs_created: int
    jobs_updated: int; listings_deactivated: int; error: str | None
    model_config = ConfigDict(from_attributes=True)

class RentalListingCreate(BaseModel):
    title: str = Field(min_length=3, max_length=250)
    locality: str = Field(min_length=2, max_length=150)
    rent: int = Field(gt=0, le=10_000_000)
    bedrooms: int = Field(ge=1, le=20)
    furnishing: str | None = Field(default=None, max_length=50)
    property_type: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    listing_url: HttpUrl | None = None
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_share_allowed: bool = False
    source_name: str = Field(default="owner", max_length=100)
    verified: bool = False

class RentalListingOut(BaseModel):
    id: int
    title: str
    locality: str
    rent: int
    bedrooms: int
    furnishing: str | None = None
    property_type: str | None = None
    description: str | None = None
    listing_url: str | None = None
    source_name: str
    verified_at: datetime | None = None
    available: bool
    model_config = ConfigDict(from_attributes=True)
