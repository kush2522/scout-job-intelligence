"""Initial schema for Scout Job Intelligence."""
from alembic import op
import sqlalchemy as sa
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("companies",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(250), nullable=False),
        sa.Column("normalized_name", sa.String(250), nullable=False), sa.Column("website_url", sa.String(1000)),
        sa.Column("careers_url", sa.String(1000)), sa.Column("industry", sa.String(200)), sa.Column("country_code", sa.String(2), server_default="IN"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("normalized_name", name="uq_companies_normalized_name"))
    op.create_index("ix_companies_name", "companies", ["name"]); op.create_index("ix_companies_normalized_name", "companies", ["normalized_name"])
    op.create_table("sources", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(250), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False), sa.Column("base_url", sa.String(1000), nullable=False), sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("robots_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)), sa.Column("last_status", sa.String(40)), sa.Column("last_error", sa.Text()),
        sa.Column("min_interval_seconds", sa.Integer(), nullable=False, server_default="2"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_sources_kind", "sources", ["kind"]); op.create_index("ix_sources_enabled", "sources", ["enabled"])
    op.create_table("jobs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("title", sa.String(500), nullable=False),
        sa.Column("normalized_title", sa.String(500), nullable=False), sa.Column("company_name", sa.String(250), nullable=False),
        sa.Column("location", sa.String(500)), sa.Column("employment_type", sa.String(120)), sa.Column("description", sa.Text()),
        sa.Column("apply_url", sa.String(1500), nullable=False), sa.Column("canonical_url", sa.String(1500), nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=False), sa.Column("remote", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("posted_at", sa.DateTime(timezone=True)), sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id")))
    for name,col in [("title","title"),("normalized_title","normalized_title"),("company_name","company_name"),("location","location"),("canonical_url","canonical_url"),("dedupe_key","dedupe_key"),("remote","remote"),("posted_at","posted_at"),("first_seen_at","first_seen_at"),("last_seen_at","last_seen_at"),("active","active"),("company_id","company_id")]: op.create_index(f"ix_jobs_{name}","jobs",[col])
    op.create_index("ix_jobs_active_first_seen", "jobs", ["active", "first_seen_at"])
    op.create_table("job_listings", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False), sa.Column("external_id", sa.String(500), nullable=False),
        sa.Column("source_job_url", sa.String(1500), nullable=False), sa.Column("canonical_url", sa.String(1500), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("source_id", "external_id", name="uq_listing_source_external"))
    for name,col in [("job_id","job_id"),("source_id","source_id"),("canonical_url","canonical_url"),("active","active")]: op.create_index(f"ix_job_listings_{name}","job_listings",[col])
    op.create_table("ingestion_runs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="SET NULL")),
        sa.Column("source_name", sa.String(250), nullable=False), sa.Column("trigger", sa.String(40), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(40), nullable=False, server_default="running"), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)), sa.Column("jobs_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_created", sa.Integer(), nullable=False, server_default="0"), sa.Column("jobs_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("listings_deactivated", sa.Integer(), nullable=False, server_default="0"), sa.Column("error", sa.Text()))
    for name,col in [("source_id","source_id"),("status","status"),("started_at","started_at")]: op.create_index(f"ix_ingestion_runs_{name}","ingestion_runs",[col])

def downgrade():
    op.drop_table("ingestion_runs"); op.drop_table("job_listings"); op.drop_table("jobs"); op.drop_table("sources"); op.drop_table("companies")
