"""Enforce one canonical Job row per deterministic dedupe key."""
from alembic import op
revision = "0004_unique_job_dedupe"
down_revision = "0003_job_salary_fields"
branch_labels = None
depends_on = None
def upgrade():
    # Before applying to a database containing imported records, review and merge duplicate dedupe_key groups.
    op.create_index("ux_jobs_dedupe_key", "jobs", ["dedupe_key"], unique=True)
def downgrade():
    op.drop_index("ux_jobs_dedupe_key", table_name="jobs")
