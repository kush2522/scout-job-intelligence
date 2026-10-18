import asyncio, hashlib, re
from urllib.parse import urlparse
import ipaddress
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .models import Job, JobListing, Source, Company, IngestionRun
from .connectors import fetch_source, canonicalize, normalize
from .config import settings

_SOURCE_LOCKS: dict[int, asyncio.Lock] = {}
_SKILL_PATTERNS = {
    "Python": r"\bpython\b", "Java": r"\bjava\b", "Scala": r"\bscala\b", "Go": r"\bgolang\b|\bgo language\b",
    "TypeScript": r"\btypescript\b", "JavaScript": r"\bjavascript\b", "React": r"\breact(?:\.js)?\b",
    "Node.js": r"\bnode(?:\.js)?\b", "AWS": r"\baws\b|amazon web services", "Azure": r"\bazure\b",
    "GCP": r"\bgcp\b|google cloud platform", "Kubernetes": r"\bkubernetes\b|\bk8s\b", "Docker": r"\bdocker\b",
    "Terraform": r"\bterraform\b", "DevOps": r"\bdevops\b", "SRE": r"\bsre\b|site reliability engineering",
    "PostgreSQL": r"\bpostgres(?:ql)?\b", "SQL": r"\bsql\b", "Apache Spark": r"\bspark\b|apache spark",
    "Kafka": r"\bkafka\b", "Databricks": r"\bdatabricks\b", "MLOps": r"\bmlops\b",
    "Generative AI": r"generative ai|\bgenai\b", "Machine Learning": r"machine learning|\bml\b",
    "LLMs": r"\bllm(?:s)?\b|large language models", "RAG": r"\brag\b|retrieval augmented generation",
    "LangChain": r"\blangchain\b", "LangGraph": r"\blanggraph\b", "PyTorch": r"\bpytorch\b",
    "TensorFlow": r"\btensorflow\b", "CI/CD": r"\bci\s*/\s*cd\b|continuous integration|continuous delivery",
    "OpenSearch": r"\bopensearch\b", "Elasticsearch": r"\belasticsearch\b", "Snowflake": r"\bsnowflake\b",
    "BigQuery": r"\bbigquery\b", "Redis": r"\bredis\b", "Postman": r"\bpostman\b"
}
def extract_skills(title: str | None, description: str | None) -> list[str]:
    text = f"{title or ''} {description or ''}".casefold()
    return sorted(name for name, pattern in _SKILL_PATTERNS.items() if re.search(pattern, text, re.IGNORECASE))
def _dedupe_key(item):
    raw = "|".join([normalize(item.get("title")), normalize(item.get("company_name")), normalize(item.get("location")), normalize(item.get("employment_type"))])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
def _company_key(name): return normalize(name)
_SOURCE_PRIORITY = {"career_page": 1, "jsonld": 1, "greenhouse": 2, "lever": 2, "ashby": 2, "smartrecruiters": 2, "adzuna": 5}
def _redact_error(exc):
    text = str(exc)
    # Provider credentials must never be persisted in ingestion-run error messages.
    for secret in (settings.adzuna_app_id, settings.adzuna_app_key):
        if secret: text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"([?&](?:app_id|app_key)=)[^&\s]+", r"\1[REDACTED]", text, flags=re.IGNORECASE)
    return text[:4000]

def _safe_job_url(url, fallback):
    try:
        parsed = urlparse(str(url))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname: return fallback
        host = parsed.hostname.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")): return fallback
        try:
            if not ipaddress.ip_address(host).is_global: return fallback
        except ValueError:
            pass
        return str(url)
    except Exception:
        return fallback

def _upsert_company(db: Session, name: str, source: Source):
    key = _company_key(name)
    company = db.scalar(select(Company).where(Company.normalized_name == key))
    cfg = source.config_json or {}
    careers_url = None if source.kind == "adzuna" else source.base_url
    if not company:
        company = Company(name=name, normalized_name=key, website_url=cfg.get("website_url"), careers_url=careers_url, country_code=cfg.get("country_code", "IN"))
        db.add(company); db.flush()
    else:
        if not company.careers_url and careers_url: company.careers_url = careers_url
        if not company.website_url and cfg.get("website_url"): company.website_url = cfg["website_url"]
    return company

async def ingest_source(db: Session, source: Source, trigger="manual"):
    if not source.terms_reviewed:
        return {"source_id": source.id, "status": "blocked", "reason": "Source terms/policy review must be recorded before ingestion"}
    if not source.enabled and trigger != "manual-approved":
        return {"source_id": source.id, "status": "skipped", "reason": "Source is disabled"}
    lock = _SOURCE_LOCKS.setdefault(source.id, asyncio.Lock())
    if lock.locked(): return {"source_id": source.id, "status": "skipped", "reason": "A run for this source is already active"}
    async with lock:
        # Enforce the configured minimum interval for this source. SQLite/dev uses this
        # process lock; production should run one worker replica until DB-level advisory
        # locking is enabled for multi-replica ingestion.
        if source.last_run_at:
            last = source.last_run_at
            if last.tzinfo is None: last = last.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            if elapsed < max(source.min_interval_seconds, settings.min_source_interval_seconds):
                return {"source_id": source.id, "status": "skipped", "reason": "Source minimum interval has not elapsed",
                        "retry_after_seconds": int(max(source.min_interval_seconds, settings.min_source_interval_seconds) - elapsed)}
        run = IngestionRun(source_id=source.id, source_name=source.name, trigger=trigger, status="running")
        db.add(run); db.commit(); db.refresh(run)
        source.last_run_at = datetime.now(timezone.utc); source.last_error = None; db.commit()
        seen_external_ids = set(); seen_count = created = updated = deactivated = 0
        try:
            async for item in fetch_source(source):
                seen_count += 1
                item["apply_url"] = _safe_job_url(item.get("apply_url"), source.base_url)
                external_id = str(item.get("external_id") or canonicalize(item["apply_url"]))
                seen_external_ids.add(external_id)
                listing = db.scalar(select(JobListing).where(JobListing.source_id == source.id, JobListing.external_id == external_id))
                dedupe = _dedupe_key(item)
                if listing:
                    original_job = db.get(Job, listing.job_id)
                    canonical_match = db.scalar(select(Job).where(Job.dedupe_key == dedupe, Job.id != listing.job_id))
                    if canonical_match:
                        # The source changed this role's identity fields into an already-known group.
                        # Repoint this source listing; delete the old canonical row only if now orphaned.
                        job = canonical_match
                        listing.job_id = canonical_match.id
                        db.flush()
                        remaining = db.scalar(select(func.count(JobListing.id)).where(JobListing.job_id == original_job.id)) or 0
                        if remaining == 0: db.delete(original_job)
                    else:
                        job = original_job
                        if job.dedupe_key != dedupe: job.dedupe_key = dedupe
                    updated += 1
                else:
                    job = db.scalar(select(Job).where(Job.dedupe_key == dedupe))
                    if job: updated += 1
                    else:
                        company = _upsert_company(db, item["company_name"], source)
                        job = Job(title=item["title"], normalized_title=normalize(item["title"]), company_name=item["company_name"],
                            location=item.get("location"), employment_type=item.get("employment_type"), description=item.get("description"),
                            apply_url=item["apply_url"], canonical_url=canonicalize(item["apply_url"]), dedupe_key=dedupe,
                            remote=bool(item.get("remote")), posted_at=item.get("posted_at"), company_id=company.id, primary_source_id=source.id)
                        db.add(job); db.flush(); created += 1
                # Prefer company-owned career pages and direct ATS links over aggregation redirects.
                current_primary = db.get(Source, job.primary_source_id) if job.primary_source_id else None
                current_priority = _SOURCE_PRIORITY.get(current_primary.kind, 3) if current_primary else 999
                new_priority = _SOURCE_PRIORITY.get(source.kind, 3)
                if not job.primary_source_id or new_priority < current_priority:
                    job.primary_source_id = source.id
                    job.apply_url = item.get("apply_url") or job.apply_url
                    job.canonical_url = canonicalize(item.get("apply_url") or job.canonical_url)
                elif job.primary_source_id == source.id and item.get("apply_url"):
                    job.apply_url = item["apply_url"]
                    job.canonical_url = canonicalize(item["apply_url"])
                # Refresh canonical values only when supplied data is not empty; preserve known details if connector lacks them.
                job.title = item.get("title") or job.title
                job.normalized_title = normalize(job.title)
                job.company_name = item.get("company_name") or job.company_name
                job.location = item.get("location") or job.location
                job.employment_type = item.get("employment_type") or job.employment_type
                job.salary_min = item.get("salary_min") if item.get("salary_min") is not None else job.salary_min
                job.salary_max = item.get("salary_max") if item.get("salary_max") is not None else job.salary_max
                job.salary_currency = item.get("salary_currency") or job.salary_currency
                job.description = item.get("description") or job.description
                job.skills_json = sorted(set(job.skills_json or []) | set(extract_skills(job.title, job.description)))
                job.posted_at = item.get("posted_at") or job.posted_at
                job.remote = bool(item.get("remote")) or job.remote
                job.active = True; job.last_seen_at = datetime.now(timezone.utc)
                if not job.company_id:
                    company = _upsert_company(db, job.company_name, source); job.company_id = company.id
                if job.company_id:
                    company_record = db.get(Company, job.company_id)
                    cfg = source.config_json or {}
                    if company_record and source.kind != "adzuna" and not company_record.careers_url:
                        company_record.careers_url = source.base_url
                    if company_record and not company_record.website_url and cfg.get("website_url"):
                        company_record.website_url = cfg["website_url"]
                    if company_record and item.get("industry") and not company_record.industry:
                        company_record.industry = str(item["industry"])[:200]
                if listing:
                    listing.job_id = job.id; listing.source_job_url = item["apply_url"]; listing.canonical_url = canonicalize(item["apply_url"])
                    listing.active = True; listing.last_seen_at = datetime.now(timezone.utc)
                else:
                    db.add(JobListing(job_id=job.id, source_id=source.id, external_id=external_id, source_job_url=item["apply_url"],
                        canonical_url=canonicalize(item["apply_url"]), active=True))
                # Commit in small batches to cap memory/transaction size for large feeds.
                if seen_count % 100 == 0: db.commit()
            # Successful full snapshot: postings absent from this feed are no longer active at this source.
            existing_listings = db.scalars(select(JobListing).where(JobListing.source_id == source.id, JobListing.active.is_(True))).all()
            for listing in existing_listings:
                if listing.external_id not in seen_external_ids:
                    listing.active = False; deactivated += 1
                    db.flush()
                    active_elsewhere = db.scalar(select(func.count(JobListing.id)).where(JobListing.job_id == listing.job_id, JobListing.active.is_(True), JobListing.id != listing.id)) or 0
                    if active_elsewhere == 0:
                        job = db.get(Job, listing.job_id)
                        if job: job.active = False
            run.status = "success"; run.jobs_seen = seen_count; run.jobs_created = created; run.jobs_updated = updated
            run.listings_deactivated = deactivated; run.finished_at = datetime.now(timezone.utc)
            source.last_status = "success"; source.last_error = None
            db.commit()
            return {"run_id": run.id, "source_id": source.id, "status": run.status, "jobs_seen": seen_count, "created": created, "updated": updated, "listings_deactivated": deactivated}
        except Exception as exc:
            db.rollback()
            # Failed/blocked sources do not cause listings to be deactivated.
            source = db.get(Source, source.id); run = db.get(IngestionRun, run.id)
            if source: source.last_status = "error"; source.last_error = _redact_error(exc)[:2000]
            if run:
                run.status = "error"; run.error = _redact_error(exc)[:4000]; run.jobs_seen = seen_count; run.jobs_created = created; run.jobs_updated = updated
                run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return {"run_id": run.id if run else None, "source_id": source.id if source else None, "status": "error", "error": _redact_error(exc)[:1000]}

async def ingest_all(db: Session, trigger="manual"):
    sources = db.scalars(select(Source).where(Source.enabled.is_(True)).order_by(Source.id)).all()
    results = []
    for source in sources:
        results.append(await ingest_source(db, source, trigger=trigger))
    return results
