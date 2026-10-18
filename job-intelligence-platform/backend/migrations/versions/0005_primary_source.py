"""Track the preferred direct application source for each canonical job."""
from alembic import op
import sqlalchemy as sa

revision = "0005_primary_source"
down_revision = "0004_unique_job_dedupe"
branch_labels = None
depends_on = None

def upgrade():
    # Batch mode keeps local SQLite migrations working; Postgres applies native ALTERs.
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("primary_source_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_jobs_primary_source_id_sources", "sources", ["primary_source_id"], ["id"])
    op.create_index("ix_jobs_primary_source_id", "jobs", ["primary_source_id"])

def downgrade():
    op.drop_index("ix_jobs_primary_source_id", table_name="jobs")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint("fk_jobs_primary_source_id_sources", type_="foreignkey")
        batch_op.drop_column("primary_source_id")
