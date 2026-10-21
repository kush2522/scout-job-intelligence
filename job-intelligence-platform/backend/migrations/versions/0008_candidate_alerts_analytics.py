"""Persist candidate accounts, saved job alerts, and search analytics."""
from alembic import op
import sqlalchemy as sa

revision = "0008_candidate_alerts_analytics"
down_revision = "0007_whatsapp_rentals"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "portal_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_portal_users_email", "portal_users", ["email"], unique=True)
    op.create_table(
        "saved_searches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("portal_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("query", sa.String(150)),
        sa.Column("location", sa.String(150)),
        sa.Column("company", sa.String(150)),
        sa.Column("remote", sa.Boolean()),
        sa.Column("employment_type", sa.String(120)),
        sa.Column("posted_within_days", sa.Integer()),
        sa.Column("frequency", sa.String(12), nullable=False, server_default="daily"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_send_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_saved_searches_user_id", "saved_searches", ["user_id"])
    op.create_index("ix_saved_searches_active", "saved_searches", ["active"])
    op.create_index("ix_saved_searches_next_send_at", "saved_searches", ["next_send_at"])
    op.create_table(
        "alerted_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("saved_search_id", sa.Integer(), sa.ForeignKey("saved_searches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("saved_search_id", "job_id", name="uq_alerted_search_job"),
    )
    op.create_index("ix_alerted_jobs_saved_search_id", "alerted_jobs", ["saved_search_id"])
    op.create_index("ix_alerted_jobs_job_id", "alerted_jobs", ["job_id"])
    op.create_table(
        "search_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("query_text", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_search_events_query_text", "search_events", ["query_text"])
    op.create_index("ix_search_events_created_at", "search_events", ["created_at"])

def downgrade():
    op.drop_table("search_events")
    op.drop_table("alerted_jobs")
    op.drop_table("saved_searches")
    op.drop_index("ix_portal_users_email", table_name="portal_users")
    op.drop_table("portal_users")
