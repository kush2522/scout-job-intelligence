"""Scheduled ingestion worker. Run as a separate process/container from the API."""
import asyncio, logging
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete
from app.config import settings
from app.db import Base, engine, SessionLocal
from app.ingest import ingest_all
from app.portal import deliver_due_alerts
from app.models import SearchEvent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
async def collect():
    with SessionLocal() as db:
        results = await ingest_all(db, trigger="scheduled")
        logging.info("scheduled ingestion finished: %s", results)
async def send_alerts():
    await deliver_due_alerts()
def prune_search_analytics():
    with SessionLocal() as db:
        db.execute(delete(SearchEvent).where(SearchEvent.created_at < datetime.now(timezone.utc) - timedelta(days=365)))
        db.commit()
async def main():
    if settings.auto_create_schema and settings.app_env != "production": Base.metadata.create_all(bind=engine)
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(collect, IntervalTrigger(minutes=max(5, settings.scheduler_interval_minutes)), id="scout-ingest",
                      replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=300)
    scheduler.add_job(send_alerts, IntervalTrigger(minutes=15), id="scout-job-alerts",
                      replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=3600)
    scheduler.add_job(prune_search_analytics, IntervalTrigger(hours=24), id="scout-search-analytics-retention",
                      replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()
    logging.info("Scheduler started; interval=%s minutes", settings.scheduler_interval_minutes)
    # Run once on startup, then continue on schedule.
    await collect()
    await send_alerts()
    prune_search_analytics()
    try:
        while True: await asyncio.sleep(3600)
    finally: scheduler.shutdown(wait=False)
if __name__ == "__main__": asyncio.run(main())
