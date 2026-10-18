"""Store extracted normalized skill tags on canonical jobs."""
from alembic import op
import sqlalchemy as sa
revision = "0006_job_skill_tags"
down_revision = "0005_primary_source"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("jobs", sa.Column("skills_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
def downgrade():
    op.drop_column("jobs", "skills_json")
