import asyncio
from datetime import datetime, timezone
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Source, Job, JobListing, Company
import app.ingest as ingest
from app.config import settings


def test_cross_source_dedup_prefers_direct_source_and_tracks_closure(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    sample = {"external_id":"ext-1", "title":"Platform Engineer", "company_name":"Example Corp",
              "location":"Bengaluru, India", "employment_type":"Full-time", "description":"A role",
              "apply_url":"https://jobs.example/role/1", "remote":False, "posted_at":datetime.now(timezone.utc)}
    data = {}
    async def fake_fetch(source):
        for item in data.get(source.id, []):
            yield dict(item)
    monkeypatch.setattr(ingest, "fetch_source", fake_fetch)
    monkeypatch.setattr(settings, "min_source_interval_seconds", 0)

    with Session() as db:
        aggregator = Source(name="Adzuna query", kind="adzuna", base_url="https://api.adzuna.com/v1/api/jobs/in/search/1",
                            config_json={"what":"platform engineer"}, enabled=True, terms_reviewed=True, min_interval_seconds=0)
        direct = Source(name="Example Corp careers", kind="greenhouse", base_url="https://boards.greenhouse.io/example",
                        config_json={"board_token":"example","company_name":"Example Corp"}, enabled=True,
                        terms_reviewed=True, min_interval_seconds=0)
        db.add_all([aggregator, direct]); db.commit(); db.refresh(aggregator); db.refresh(direct)
        data[aggregator.id] = [dict(sample, apply_url="https://adzuna.example/redirect/1")]
        data[direct.id] = [dict(sample, apply_url="https://boards.greenhouse.io/example/jobs/1")]
        first = asyncio.run(ingest.ingest_source(db, aggregator))
        second = asyncio.run(ingest.ingest_source(db, direct))
        assert first["status"] == "success"
        assert second["status"] == "success"
        assert db.scalar(select(func.count(Job.id))) == 1
        job = db.scalar(select(Job))
        assert job.primary_source_id == direct.id
        assert job.apply_url == "https://boards.greenhouse.io/example/jobs/1"
        company = db.get(Company, job.company_id)
        assert company.careers_url == direct.base_url
        assert db.scalar(select(func.count(JobListing.id)).where(JobListing.active.is_(True))) == 2

        # A complete successful snapshot closes missing source listings but preserves the job while one source still has it.
        data[aggregator.id] = []
        result = asyncio.run(ingest.ingest_source(db, aggregator))
        assert result["status"] == "success"
        job = db.scalar(select(Job))
        assert job.active is True
        assert db.scalar(select(func.count(JobListing.id)).where(JobListing.active.is_(True))) == 1

        data[direct.id] = []
        result = asyncio.run(ingest.ingest_source(db, direct))
        assert result["status"] == "success"
        assert db.scalar(select(Job.active).where(Job.id == job.id)) is False
    engine.dispose()
