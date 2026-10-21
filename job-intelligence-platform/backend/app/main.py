from contextlib import asynccontextmanager
import csv, io
from datetime import datetime, timedelta, timezone
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, or_, func, desc
from sqlalchemy.orm import Session
from .config import settings
from .db import Base, engine, get_db
from .models import Job, JobListing, Source, Company, IngestionRun, RentalListing
from .schemas import SourceCreate, SourceOut, JobOut, CompanyOut, SourceRunOut, RentalListingCreate, RentalListingOut
from .ingest import ingest_source, ingest_all
from .connectors import assert_public_http_url
from .security import require_admin
from .discovery import discover_careers, connector_for_url
from .whatsapp import router as whatsapp_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_schema and settings.app_env != "production":
        Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(title="Scout Job Intelligence API", version="0.2.0", lifespan=lifespan,
              description="Multi-source job ingestion and hiring intelligence API")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],
                   allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "OPTIONS"], allow_headers=["Content-Type", "X-Admin-Token"])
app.include_router(whatsapp_router)

def _is_recently_seen(job: Job, days: int = 30) -> bool:
    last_seen = job.last_seen_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return last_seen >= datetime.now(timezone.utc) - timedelta(days=days)

@app.post("/api/admin/rentals", response_model=RentalListingOut, dependencies=[Depends(require_admin)])
def create_rental(payload: RentalListingCreate, db: Session = Depends(get_db)):
    item = RentalListing(
        title=payload.title, locality=payload.locality, rent=payload.rent, bedrooms=payload.bedrooms,
        furnishing=payload.furnishing, property_type=payload.property_type, description=payload.description,
        listing_url=str(payload.listing_url) if payload.listing_url else None,
        contact_phone=payload.contact_phone, contact_share_allowed=payload.contact_share_allowed,
        source_name=payload.source_name, verified_at=datetime.now(timezone.utc) if payload.verified else None,
    )
    db.add(item); db.commit(); db.refresh(item); return item

@app.get("/api/admin/rentals", response_model=list[RentalListingOut], dependencies=[Depends(require_admin)])
def list_rentals(available: bool | None = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    stmt = select(RentalListing).order_by(desc(RentalListing.updated_at)).limit(limit)
    if available is not None: stmt = stmt.where(RentalListing.available.is_(available))
    return db.scalars(stmt).all()

@app.patch("/api/admin/rentals/{listing_id}", dependencies=[Depends(require_admin)])
def update_rental(listing_id: int, payload: dict, db: Session = Depends(get_db)):
    item = db.get(RentalListing, listing_id)
    if not item: raise HTTPException(404, "Rental listing not found")
    allowed = {"available", "verified", "rent", "locality", "title", "bedrooms", "furnishing", "property_type", "description", "listing_url", "contact_phone", "contact_share_allowed"}
    unknown = set(payload) - allowed
    if unknown: raise HTTPException(422, f"Unsupported fields: {', '.join(sorted(unknown))}")
    for key, value in payload.items():
        if key == "verified": item.verified_at = datetime.now(timezone.utc) if value else None
        elif key == "listing_url": item.listing_url = str(value) if value else None
        elif hasattr(item, key): setattr(item, key, value)
    db.commit(); db.refresh(item); return {"id": item.id, "available": item.available, "verified_at": item.verified_at}

@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(select(func.count(Job.id)))
        return {"status": "ok", "database": "reachable", "environment": settings.app_env}
    except Exception:
        raise HTTPException(503, "Database unavailable")

@app.get("/api/jobs", response_model=list[JobOut])
def jobs(q: str | None = None, location: str | None = None, company: str | None = None,
         employment_type: str | None = None, remote: bool | None = None, posted_within_days: int | None = Query(None, ge=1, le=365),
         fresh_within_days: int = Query(30, ge=1, le=365),
         limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    source_counts = (select(JobListing.job_id.label("job_id"), func.count(func.distinct(JobListing.source_id)).label("source_count"))
                     .where(JobListing.active.is_(True)).group_by(JobListing.job_id).subquery())
    stmt = (select(Job, func.coalesce(source_counts.c.source_count, 0).label("source_count"))
            .outerjoin(source_counts, source_counts.c.job_id == Job.id)
            .where(Job.active.is_(True), Job.last_seen_at >= datetime.now(timezone.utc) - timedelta(days=fresh_within_days)))
    if q:
        like = f"%{q[:150]}%"
        stmt = stmt.where(or_(Job.title.ilike(like), Job.company_name.ilike(like), Job.description.ilike(like)))
    if location: stmt = stmt.where(Job.location.ilike(f"%{location[:150]}%"))
    if company: stmt = stmt.where(Job.company_name.ilike(f"%{company[:150]}%"))
    if employment_type: stmt = stmt.where(Job.employment_type.ilike(f"%{employment_type[:100]}%"))
    if remote is not None: stmt = stmt.where(Job.remote.is_(remote))
    if posted_within_days: stmt = stmt.where(Job.first_seen_at >= datetime.now(timezone.utc) - timedelta(days=posted_within_days))
    rows = db.execute(stmt.order_by(desc(Job.first_seen_at), Job.id).offset(offset).limit(limit)).all()
    result = []
    for job, source_count in rows:
        result.append(JobOut(id=job.id, title=job.title, company_name=job.company_name, location=job.location,
            employment_type=job.employment_type, description=job.description, salary_min=float(job.salary_min) if job.salary_min is not None else None, salary_max=float(job.salary_max) if job.salary_max is not None else None, salary_currency=job.salary_currency, skills=job.skills_json or [], apply_url=job.apply_url, canonical_url=job.canonical_url,
            remote=job.remote, posted_at=job.posted_at, first_seen_at=job.first_seen_at, last_seen_at=job.last_seen_at, active=job.active, source_count=source_count))
    return result

@app.get("/api/jobs/{job_id}/sources")
def job_sources(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    rows = db.execute(select(JobListing, Source).join(Source, JobListing.source_id == Source.id)
        .where(JobListing.job_id == job_id, JobListing.active.is_(True)).order_by(Source.name)).all()
    return [{"source_name": source.name, "source_kind": source.kind, "listing_url": listing.source_job_url,
             "last_seen_at": listing.last_seen_at} for listing, source in rows]

@app.get("/api/jobs/{job_id}", response_model=JobOut)
def job_detail(job_id: int, fresh_within_days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or not job.active or not _is_recently_seen(job, fresh_within_days): raise HTTPException(404, "Active job not found")
    source_count = db.scalar(select(func.count(func.distinct(JobListing.source_id))).where(JobListing.job_id == job.id, JobListing.active.is_(True))) or 0
    return JobOut(id=job.id, title=job.title, company_name=job.company_name, location=job.location, employment_type=job.employment_type,
        description=job.description, salary_min=float(job.salary_min) if job.salary_min is not None else None, salary_max=float(job.salary_max) if job.salary_max is not None else None, salary_currency=job.salary_currency, skills=job.skills_json or [], apply_url=job.apply_url, canonical_url=job.canonical_url, remote=job.remote, posted_at=job.posted_at,
        first_seen_at=job.first_seen_at, last_seen_at=job.last_seen_at, active=job.active, source_count=source_count)

@app.get("/api/companies", response_model=list[CompanyOut])
def companies(q: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    active_counts = (select(Job.company_id.label("company_id"), func.count(Job.id).label("active_job_count"))
                     .where(Job.active.is_(True), Job.last_seen_at >= datetime.now(timezone.utc) - timedelta(days=30))
                     .group_by(Job.company_id).subquery())
    stmt = select(Company, func.coalesce(active_counts.c.active_job_count, 0)).outerjoin(active_counts, active_counts.c.company_id == Company.id)
    if q: stmt = stmt.where(Company.name.ilike(f"%{q[:150]}%"))
    items = db.execute(stmt.order_by(Company.name).offset(offset).limit(limit)).all()
    out = []
    for c, count in items:
        out.append(CompanyOut(id=c.id, name=c.name, website_url=c.website_url, careers_url=c.careers_url, industry=c.industry, country_code=c.country_code, active_job_count=count))
    return out

@app.get("/api/sources", response_model=list[SourceOut])
def sources(db: Session = Depends(get_db)):
    # Public view deliberately excludes connector configuration and credentials.
    return db.scalars(select(Source).order_by(Source.name)).all()

@app.get("/api/analytics/overview")
def analytics_overview(db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=7)
    fresh = datetime.now(timezone.utc) - timedelta(days=30)
    return {"active_jobs": db.scalar(select(func.count(Job.id)).where(Job.active.is_(True), Job.last_seen_at >= fresh)) or 0,
            "companies": db.scalar(select(func.count(Company.id))) or 0,
            "enabled_sources": db.scalar(select(func.count(Source.id)).where(Source.enabled.is_(True))) or 0,
            "new_jobs_7d": db.scalar(select(func.count(Job.id)).where(Job.active.is_(True), Job.last_seen_at >= fresh, Job.first_seen_at >= since)) or 0,
            "source_count": len(db.scalars(select(Source.id)).all())}

@app.get("/api/analytics/top-companies")
def top_companies(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    active_count = func.count(Job.id).label("active_jobs")
    rows = db.execute(select(Company.name, active_count).join(Job, Job.company_id == Company.id)
        .where(Job.active.is_(True), Job.last_seen_at >= datetime.now(timezone.utc) - timedelta(days=30)).group_by(Company.id, Company.name).order_by(active_count.desc()).limit(limit)).all()
    return [{"company": name, "active_jobs": count} for name, count in rows]

@app.get("/api/analytics/locations")
def top_locations(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    active_count = func.count(Job.id).label("active_jobs")
    rows = db.execute(select(Job.location, active_count).where(Job.active.is_(True), Job.last_seen_at >= datetime.now(timezone.utc) - timedelta(days=30), Job.location.is_not(None))
        .group_by(Job.location).order_by(active_count.desc()).limit(limit)).all()
    return [{"location": location, "active_jobs": count} for location, count in rows]

@app.get("/api/analytics/roles")
def top_roles(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    role_count = func.count(Job.id).label("active_jobs")
    rows = db.execute(select(Job.normalized_title, role_count).where(Job.active.is_(True), Job.last_seen_at >= datetime.now(timezone.utc) - timedelta(days=30))
        .group_by(Job.normalized_title).order_by(role_count.desc()).limit(limit)).all()
    return [{"role": role.title() if role else "Unspecified", "active_jobs": count} for role, count in rows]

@app.get("/api/analytics/skills")
def top_skills(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    from collections import Counter
    rows = db.scalars(select(Job.skills_json).where(Job.active.is_(True), Job.last_seen_at >= datetime.now(timezone.utc) - timedelta(days=30))).all()
    counts = Counter(skill for skills in rows for skill in (skills or []))
    return [{"skill": skill, "active_jobs": count} for skill, count in counts.most_common(limit)]

@app.post("/api/admin/companies/import-csv", dependencies=[Depends(require_admin)])
async def import_companies_csv(request: Request, db: Session = Depends(get_db)):
    """Import companies from raw CSV (text/csv). Expected columns: name, website_url, careers_url, industry, country_code."""
    body = await request.body()
    if len(body) > 5 * 1024 * 1024: raise HTTPException(413, "CSV must be 5 MB or smaller")
    try: text = body.decode("utf-8-sig")
    except UnicodeDecodeError: raise HTTPException(400, "CSV must be UTF-8 encoded")
    try: rows = list(csv.DictReader(io.StringIO(text)))
    except Exception as exc: raise HTTPException(400, f"Could not parse CSV: {exc}")
    if len(rows) > 2000: raise HTTPException(413, "Maximum 2,000 companies per import")
    if not rows or not ({"name", "company_name"} & set(rows[0].keys())):
        raise HTTPException(400, "CSV needs a name or company_name column")
    companies_created=0; sources_created=0; errors=[]
    for line, row in enumerate(rows, start=2):
        name=(row.get("name") or row.get("company_name") or "").strip()
        if not name: errors.append({"line":line,"error":"Missing name"}); continue
        website=(row.get("website_url") or "").strip() or None
        careers=(row.get("careers_url") or "").strip() or None
        try:
            if website: assert_public_http_url(website)
            if careers: assert_public_http_url(careers)
            normalized=" ".join(name.casefold().split())
            company=db.scalar(select(Company).where(Company.normalized_name==normalized))
            if not company:
                company=Company(name=name,normalized_name=normalized,website_url=website,careers_url=careers,
                                industry=(row.get("industry") or "").strip() or None,country_code=(row.get("country_code") or "IN").strip().upper()[:2])
                db.add(company); db.flush(); companies_created+=1
            else:
                if website and not company.website_url: company.website_url=website
                if careers and not company.careers_url: company.careers_url=careers
            if careers:
                guess=connector_for_url(careers,name)
                exists=db.scalar(select(Source).where(Source.base_url==careers,Source.kind==guess["kind"]))
                if not exists:
                    cfg=dict(guess["config_json"]); cfg["company_name"]=name
                    if website: cfg["website_url"]=website
                    terms_reviewed=(row.get("terms_reviewed") or "").strip().lower() in {"true","yes","1","approved"}
                    src=Source(name=name,kind=guess["kind"],base_url=careers,config_json=cfg,enabled=terms_reviewed,
                               terms_reviewed=terms_reviewed, terms_review_url=(row.get("terms_review_url") or "").strip() or None,
                               min_interval_seconds=max(int(settings.min_source_interval_seconds),2))
                    db.add(src); sources_created+=1
        except Exception as exc:
            errors.append({"line":line,"company":name,"error":str(exc)[:250]})
    db.commit()
    return {"rows_received":len(rows),"companies_created":companies_created,"sources_created":sources_created,"errors":errors[:100]}

@app.get("/api/admin/discover-careers", dependencies=[Depends(require_admin)])
async def discover_company_careers(website_url: str, company_name: str | None = None):
    try: return await discover_careers(website_url, company_name)
    except PermissionError as exc: raise HTTPException(403, str(exc))
    except ValueError as exc: raise HTTPException(400, str(exc))
    except Exception as exc: raise HTTPException(502, f"Discovery failed: {str(exc)[:250]}")

@app.post("/api/admin/sources", response_model=SourceOut, dependencies=[Depends(require_admin)])
def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    url = str(payload.base_url)
    try: assert_public_http_url(url)
    except ValueError as exc: raise HTTPException(400, str(exc))
    if payload.kind in {"greenhouse", "lever", "ashby", "smartrecruiters"}:
        required = {"greenhouse": "board_token", "lever": "site", "ashby": "job_board_name", "smartrecruiters": "company_identifier"}[payload.kind]
        if not payload.config_json.get(required): raise HTTPException(422, f"config_json.{required} is required for {payload.kind}")
    if payload.kind == "adzuna" and (not payload.config_json.get("what") and not payload.config_json.get("where")):
        raise HTTPException(422, "adzuna sources should set at least config_json.what or config_json.where")
    cfg = dict(payload.config_json)
    if payload.company_name: cfg["company_name"] = payload.company_name
    if payload.website_url: cfg["website_url"] = str(payload.website_url)
    src = Source(name=payload.name, kind=payload.kind, base_url=url, config_json=cfg,
                 enabled=payload.enabled and payload.terms_reviewed, terms_reviewed=payload.terms_reviewed,
                 terms_review_url=str(payload.terms_review_url) if payload.terms_review_url else None,
                 policy_reviewed_at=datetime.now(timezone.utc) if payload.terms_reviewed else None,
                 min_interval_seconds=max(payload.min_interval_seconds, int(settings.min_source_interval_seconds)))
    if payload.enabled and not payload.terms_reviewed:
        src.last_status = "pending_review"
    db.add(src)
    company_name = payload.company_name or cfg.get("company_name") or payload.name
    normalized = " ".join(company_name.casefold().split())
    company = db.scalar(select(Company).where(Company.normalized_name == normalized))
    if not company:
        company = Company(name=company_name, normalized_name=normalized, website_url=str(payload.website_url) if payload.website_url else None,
                          careers_url=url, country_code=cfg.get("country_code", "IN"))
        db.add(company)
    else:
        company.careers_url = company.careers_url or url
        company.website_url = company.website_url or (str(payload.website_url) if payload.website_url else None)
    db.commit(); db.refresh(src); return src

@app.patch("/api/admin/sources/{source_id}", response_model=SourceOut, dependencies=[Depends(require_admin)])
def update_source(source_id: int, payload: dict, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source: raise HTTPException(404, "Source not found")
    if "terms_reviewed" in payload:
        source.terms_reviewed = bool(payload["terms_reviewed"])
        source.policy_reviewed_at = datetime.now(timezone.utc) if source.terms_reviewed else None
        if not source.terms_reviewed: source.enabled = False
        elif payload.get("enabled", source.enabled): source.enabled = True
    if "terms_review_url" in payload:
        source.terms_review_url = str(payload["terms_review_url"])[:1000] if payload["terms_review_url"] else None
    if "enabled" in payload:
        requested = bool(payload["enabled"])
        if requested and not source.terms_reviewed: raise HTTPException(409, "Review source terms and set terms_reviewed=true before enabling")
        source.enabled = requested
    if "name" in payload and isinstance(payload["name"], str): source.name = payload["name"][:250]
    if "min_interval_seconds" in payload:
        value = int(payload["min_interval_seconds"])
        if value < 1 or value > 3600: raise HTTPException(422, "min_interval_seconds must be between 1 and 3600")
        source.min_interval_seconds = max(value, int(settings.min_source_interval_seconds))
    db.commit(); db.refresh(source); return source

@app.post("/api/admin/ingest/{source_id}", dependencies=[Depends(require_admin)])
async def run_ingest(source_id: int, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source: raise HTTPException(404, "Source not found")
    if not source.enabled: raise HTTPException(400, "Source is disabled")
    return await ingest_source(db, source, trigger="manual")

@app.post("/api/admin/ingest-all", dependencies=[Depends(require_admin)])
async def run_all(db: Session = Depends(get_db)): return await ingest_all(db, trigger="manual")

@app.get("/api/admin/runs", response_model=list[SourceRunOut], dependencies=[Depends(require_admin)])
def runs(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    return db.scalars(select(IngestionRun).order_by(desc(IngestionRun.started_at)).limit(limit)).all()

@app.get("/api/admin/source-config/{source_id}", dependencies=[Depends(require_admin)])
def source_config(source_id: int, db: Session = Depends(get_db)):
    src = db.get(Source, source_id)
    if not src: raise HTTPException(404, "Source not found")
    # Config can contain identifiers; never store provider secrets here.
    return {"id": src.id, "config_json": src.config_json}
