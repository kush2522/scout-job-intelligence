"""Add source policy-review gate."""
from alembic import op
import sqlalchemy as sa
revision = "0002_source_policy_review"
down_revision = "0001_initial"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("sources", sa.Column("terms_reviewed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("sources", sa.Column("terms_review_url", sa.String(1000), nullable=True))
    op.add_column("sources", sa.Column("policy_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    # Existing sources must be re-reviewed before ingestion; disable them until approved.
    op.execute("UPDATE sources SET enabled = FALSE, last_status = 'pending_review'")
def downgrade():
    op.drop_column("sources", "policy_reviewed_at")
    op.drop_column("sources", "terms_review_url")
    op.drop_column("sources", "terms_reviewed")
