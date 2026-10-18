"""Store published salary ranges where source supplies them."""
from alembic import op
import sqlalchemy as sa
revision = "0003_job_salary_fields"
down_revision = "0002_source_policy_review"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("jobs", sa.Column("salary_min", sa.Numeric(14, 2), nullable=True))
    op.add_column("jobs", sa.Column("salary_max", sa.Numeric(14, 2), nullable=True))
    op.add_column("jobs", sa.Column("salary_currency", sa.String(3), nullable=True))
def downgrade():
    op.drop_column("jobs", "salary_currency")
    op.drop_column("jobs", "salary_max")
    op.drop_column("jobs", "salary_min")
