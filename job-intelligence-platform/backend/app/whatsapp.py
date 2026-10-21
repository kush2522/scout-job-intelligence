"""WhatsApp Cloud API webhook and guided rental search conversation."""
import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import RentalListing, WhatsAppUser

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])

def _configured():
    if not (settings.whatsapp_access_token and settings.whatsapp_phone_number_id and settings.whatsapp_verify_token and settings.whatsapp_app_secret):
        raise HTTPException(503, "WhatsApp Cloud API credentials are not configured")

@router.get("/webhook")
def verify_webhook(
    mode: str | None = Query(None, alias="hub.mode"),
    token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str | None = Query(None, alias="hub.challenge"),
):
    _configured()
    if mode == "subscribe" and hmac.compare_digest(token or "", settings.whatsapp_verify_token):
        return Response(content=challenge or "", media_type="text/plain")
    raise HTTPException(403, "Webhook verification failed")

async def send_text(to: str, body: str):
    _configured()
    url = f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{settings.whatsapp_phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
               "type": "text", "text": {"preview_url": True, "body": body[:4000]}}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, headers=headers, json=payload)
    response.raise_for_status()

def parse_budget(text: str) -> int | None:
    raw = text.lower().replace(",", "").replace("₹", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(k|l|lac|lakh)?", raw)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit == "k": value *= 1_000
    elif unit in {"l", "lac", "lakh"}: value *= 100_000
    amount = int(value)
    return amount if 5_000 <= amount <= 2_000_000 else None

def get_matches(db: Session, prefs: dict):
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    stmt = select(RentalListing).where(
        RentalListing.available.is_(True), RentalListing.verified_at.is_not(None),
        RentalListing.verified_at >= cutoff, RentalListing.rent <= prefs["budget"],
        RentalListing.locality.ilike(f"%{prefs['locality'][:120]}%"),
    )
    if prefs.get("bedrooms"):
        stmt = stmt.where(RentalListing.bedrooms == prefs["bedrooms"])
    return db.scalars(stmt.order_by(RentalListing.rent, RentalListing.updated_at.desc()).limit(3)).all()

def format_matches(matches: list[RentalListing], prefs: dict) -> str:
    if not matches:
        return (f"I don’t have a recently owner-confirmed match for {prefs['locality']} under ₹{prefs['budget']:,} yet. "
                "Try a nearby locality, a higher budget, or send SEARCH to change your filters. I’ll only show homes confirmed available in the last 14 days.")
    parts = [f"I found {len(matches)} recently confirmed option(s):"]
    for i, item in enumerate(matches, 1):
        line = f"{i}. {item.title} · {item.locality} · {item.bedrooms} BHK · ₹{item.rent:,}/month"
        if item.furnishing: line += f" · {item.furnishing}"
        if item.listing_url: line += f"\n{item.listing_url}"
        if item.contact_phone and item.contact_share_allowed:
            digits = re.sub(r"\D", "", item.contact_phone)
            if digits: line += f"\nOwner WhatsApp: https://wa.me/{digits}"
        line += f"\nOwner confirmed {item.verified_at.strftime('%d %b')}"
        parts.append(line)
    parts.append("Reply SEARCH to change your search, or STOP to opt out.")
    return "\n\n".join(parts)

async def handle_text(phone: str, text: str, db: Session):
    msg = text.strip()
    command = msg.casefold()
    user = db.scalar(select(WhatsAppUser).where(WhatsAppUser.phone == phone))
    if not user:
        user = WhatsAppUser(phone=phone, state="new", preferences_json={})
        db.add(user); db.flush()
    user.last_inbound_at = datetime.now(timezone.utc)
    if command in {"stop", "unsubscribe", "opt out"}:
        user.opted_out = True; db.commit()
        await send_text(phone, "You’re opted out and won’t receive more property messages. Send START if you want to search again.")
        return
    if command == "start":
        user.opted_out = False; user.state = "locality"; user.preferences_json = {}; db.commit()
        await send_text(phone, "Hi! I’ll find rental homes in Bengaluru using listings recently confirmed available by owners. Which locality should I search? (Example: Indiranagar)")
        return
    if user.opted_out:
        if command not in {"start", "hi", "hello"}:
            return
        user.opted_out = False
    if command in {"hi", "hello", "hey", "search"}:
        user.state = "locality"; user.preferences_json = {}; db.commit()
        await send_text(phone, "Let’s find a home in Bengaluru. Which one locality should I search? (Example: HSR Layout)")
        return
    if command == "reset":
        user.state = "locality"; user.preferences_json = {}; db.commit()
        await send_text(phone, "Search reset. Which Bengaluru locality should I look in?")
        return

    if user.state in {"new", "locality"}:
        if len(msg) < 2 or len(msg) > 120:
            await send_text(phone, "Please send a locality name, such as Whitefield, HSR Layout, or Jayanagar."); return
        user.preferences_json = {"locality": msg}; user.state = "budget"; db.commit()
        await send_text(phone, f"Got it: {msg}. What’s your maximum monthly rent? (For example, 30000 or 30k)")
        return
    if user.state == "budget":
        budget = parse_budget(msg)
        if not budget:
            await send_text(phone, "Please send a monthly budget between ₹5,000 and ₹20 lakh, e.g. 30000 or 30k."); return
        prefs = dict(user.preferences_json or {}); prefs["budget"] = budget
        user.preferences_json = prefs; user.state = "bedrooms"; db.commit()
        await send_text(phone, "How many bedrooms? Reply 1, 2, 3, or ANY."); return
    if user.state == "bedrooms":
        m = re.search(r"\b(1|2|3|4)\b", msg)
        if not m and command not in {"any", "no preference", "doesn't matter"}:
            await send_text(phone, "Please reply 1, 2, 3, 4, or ANY."); return
        prefs = dict(user.preferences_json or {})
        if m: prefs["bedrooms"] = int(m.group(1))
        user.preferences_json = prefs; user.state = "ready"; db.commit()
        matches = get_matches(db, prefs)
        await send_text(phone, format_matches(matches, prefs)); return
    if user.state == "ready":
        await send_text(phone, "Send SEARCH to start a new search, or STOP to opt out."); return
    user.state = "locality"; user.preferences_json = {}; db.commit()
    await send_text(phone, "Let’s start over. Which Bengaluru locality should I search?")

@router.post("/webhook")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    _configured()
    raw = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(settings.whatsapp_app_secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                if message.get("type") != "text":
                    continue
                phone = message.get("from", "")
                body = message.get("text", {}).get("body", "")
                if phone and body:
                    try:
                        await handle_text(phone, body, db)
                    except httpx.HTTPError:
                        # Avoid Meta retries creating duplicate replies; the user can message again.
                        db.rollback()
    return {"status": "ok"}
