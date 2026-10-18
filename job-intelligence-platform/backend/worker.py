"""Scheduled ingestion worker. Run as a separate process/container from the API."""
import asyncio, logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.config import settings
from app.db import Base, engine, SessionLocal
from app.ingest import ingest_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
async def collect():
    with SessionLocal() as db:
        results = await ingest_all(db, trigger="scheduled")
        logging.info("scheduled ingestion finished: %s", results)
async def main():
    if settings.auto_create_schema and settings.app_env != "production": Base.metadata.create_all(bind=engine)
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(collect, IntervalTrigger(minutes=max(5, settings.scheduler_interval_minutes)), id="scout-ingest",
                      replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=300)
    scheduler.start()
    logging.info("Scheduler started; interval=%s minutes", settings.scheduler_interval_minutes)
    # Run once on startup, then continue on schedule.
    await collect()
    try:
        while True: await asyncio.sleep(3600)
    finally: scheduler.shutdown(wait=False)
if __name__ == "__main__": asyncio.run(main())
