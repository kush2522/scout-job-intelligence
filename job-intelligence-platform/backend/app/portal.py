"""Candidate account endpoints and scheduled email job alerts."""
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
import hashlib
import hmac
import html
import logging
import re

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, or_, and_, desc
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, get_db
from .models import AlertedJob, Job, PortalUser, SavedSearch

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portal", tags=["candidate portal"])

class SavedSearchCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    query: str | None = Field(default=None, max_length=150)
    location: str | None = Field(default=None, max_length=150)
    company: str | None = Field(default=None, max_length=150)
    remote: bool | None = None
    employment_type: str | None = Field(default=None, max_length=120)
    posted_within_days: int | None = Field(default=None, ge=1, le=365)
    frequency: str = Field(default="daily", pattern="^(daily|weekly|monthly)$")

class SavedSearchUpdate(BaseModel):
    active: bool | None = None
    frequency: str | None = Field(default=None, pattern="^(daily|weekly|monthly)$")

def require_portal_email(
    email: str | None = Header(default=None, alias="X-Portal-Email"),
    timestamp: str | None = Header(default=None, alias="X-Portal-Timestamp"),
    signature: str | None = Header(default=None, alias="X-Portal-Signature"),
) -> str:
    secret = settings.portal_identity_secret
    if not secret or not email or not timestamp or not signature:
        raise HTTPException(401, "Sign in to manage saved searches")
    try:
        issued = int(timestamp)
    except ValueError:
        raise HTTPException(401, "Invalid portal identity")
    if abs(int(datetime.now(timezone.utc).timestamp()) - issued) > 300:
        raise HTTPException(401, "Portal identity expired")
    normalized = email.strip().lower()
    expected = hmac.new(secret.encode(), f"{timestamp}.{normalized}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature) or len(normalized) > 320:
        raise HTTPException(401, "Invalid portal identity")
    return normalized

def _user_for(db: Session, email: str) -> PortalUser:
    user = db.scalar(select(PortalUser).where(PortalUser.email == email))
    if user is None:
        user = PortalUser(email=email)
        db.add(user)
        db.flush()
    return user

def _out(item: SavedSearch) -> dict:
    return {"id": item.id, "name": item.name, "query": item.query, "location": item.location,
            "company": item.company, "remote": item.remote, "frequency": item.frequency,
            "employment_type": item.employment_type, "posted_within_days": item.posted_within_days,
            "active": item.active, "created_at": item.created_at, "last_sent_at": item.last_sent_at}

@router.get("/saved-searches")
def list_saved_searches(email: str = Depends(require_portal_email), db: Session = Depends(get_db)):
    user = _user_for(db, email)
    db.commit()
    items = db.scalars(select(SavedSearch).where(SavedSearch.user_id == user.id).order_by(desc(SavedSearch.created_at))).all()
    return [_out(item) for item in items]

@router.post("/saved-searches")
def create_saved_search(payload: SavedSearchCreate, email: str = Depends(require_portal_email), db: Session = Depends(get_db)):
    filters = {key: (value.strip() if isinstance(value, str) else value) for key, value in payload.model_dump().items()}
    if not any(filters[key] for key in ("query", "location", "company", "employment_type")) and filters["remote"] is None and filters["posted_within_days"] is None:
        raise HTTPException(422, "Add a title, keyword, company, location, or remote filter")
    user = _user_for(db, email)
    item = SavedSearch(user_id=user.id, **filters, next_send_at=datetime.now(timezone.utc))
    db.add(item); db.commit(); db.refresh(item)
    result = _out(item)
    result["email_delivery_configured"] = bool(settings.resend_api_key)
    return result

@router.patch("/saved-searches/{search_id}")
def update_saved_search(search_id: int, payload: SavedSearchUpdate, email: str = Depends(require_portal_email), db: Session = Depends(get_db)):
    item = db.scalar(select(SavedSearch).join(PortalUser).where(SavedSearch.id == search_id, PortalUser.email == email))
    if not item: raise HTTPException(404, "Saved search not found")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items(): setattr(item, key, value)
    if "frequency" in changes: item.next_send_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(item)
    return _out(item)

@router.delete("/saved-searches/{search_id}")
def delete_saved_search(search_id: int, email: str = Depends(require_portal_email), db: Session = Depends(get_db)):
    item = db.scalar(select(SavedSearch).join(PortalUser).where(SavedSearch.id == search_id, PortalUser.email == email))
    if not item: raise HTTPException(404, "Saved search not found")
    db.delete(item); db.commit()
    return {"deleted": True}

def _matches(db: Session, saved: SavedSearch):
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    stmt = select(Job).where(Job.active.is_(True), Job.last_seen_at >= cutoff)
    if saved.query:
        like = f"%{saved.query[:150]}%"
        stmt = stmt.where(or_(Job.title.ilike(like), Job.company_name.ilike(like), Job.description.ilike(like)))
    if saved.location: stmt = stmt.where(Job.location.ilike(f"%{saved.location[:150]}%"))
    if saved.company: stmt = stmt.where(Job.company_name.ilike(f"%{saved.company[:150]}%"))
    if saved.remote is not None: stmt = stmt.where(Job.remote.is_(saved.remote))
    if saved.employment_type: stmt = stmt.where(Job.employment_type.ilike(f"%{saved.employment_type[:120]}%"))
    if saved.posted_within_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=saved.posted_within_days)
        stmt = stmt.where(or_(and_(Job.posted_at.is_not(None), Job.posted_at >= cutoff), and_(Job.posted_at.is_(None), Job.first_seen_at >= cutoff)))
    already_sent = select(AlertedJob.job_id).where(AlertedJob.saved_search_id == saved.id)
    return db.scalars(stmt.where(Job.id.not_in(already_sent)).order_by(desc(Job.first_seen_at)).limit(20)).all()

def _email_html(saved: SavedSearch, jobs: list[Job]) -> str:
    cards = []
    for job in jobs:
        title, company = html.escape(job.title), html.escape(job.company_name)
        location = html.escape(job.location or "Location not specified")
        url = html.escape(job.apply_url, quote=True)
        cards.append(f'<li style="padding:16px 0;border-bottom:1px solid #e5e7eb"><strong>{title}</strong><br>{company} · {location}<br><a href="{url}">View original listing</a></li>')
    preferences_url = html.escape(settings.portal_base_url.rstrip("/") + "/#jobs", quote=True)
    return f'<div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;color:#0f172a"><h1>New roles for {html.escape(saved.name)}</h1><p>Here are new jobs matching your saved search.</p><ul style="list-style:none;padding:0">{"".join(cards)}</ul><p style="font-size:12px;color:#64748b"><a href="{preferences_url}">Manage or pause your alerts</a></p></div>'

async def deliver_due_alerts() -> None:
    if not settings.resend_api_key:
        return
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        due = db.scalars(select(SavedSearch).where(SavedSearch.active.is_(True), SavedSearch.next_send_at <= now).order_by(SavedSearch.id).limit(200)).all()
        for saved in due:
            user = db.get(PortalUser, saved.user_id)
            if not user or not parseaddr(user.email)[1]:
                saved.next_send_at = now + timedelta(hours=1); db.commit(); continue
            matches = _matches(db, saved)
            if not matches:
                saved.next_send_at = _next_due(now, saved.frequency); db.commit(); continue
            payload = {"from": settings.alert_email_from, "to": [user.email],
                       "subject": f"{len(matches)} new job{'s' if len(matches) != 1 else ''} for {saved.name}",
                       "html": _email_html(saved, matches)}
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.post("https://api.resend.com/emails", json=payload,
                                                 headers={"Authorization": f"Bearer {settings.resend_api_key}"})
                    response.raise_for_status()
                db.add_all([AlertedJob(saved_search_id=saved.id, job_id=job.id) for job in matches])
                saved.last_sent_at = now
                saved.next_send_at = _next_due(now, saved.frequency)
                db.commit()
            except Exception:
                db.rollback()
                log.exception("Could not deliver alert for saved search %s", saved.id)
                saved = db.get(SavedSearch, saved.id)
                if saved:
                    saved.next_send_at = now + timedelta(hours=1)
                    db.commit()

def _next_due(now: datetime, frequency: str) -> datetime:
    return now + {"daily": timedelta(days=1), "weekly": timedelta(days=7), "monthly": timedelta(days=30)}.get(frequency, timedelta(days=1))
