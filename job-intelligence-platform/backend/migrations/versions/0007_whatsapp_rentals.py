"""WhatsApp rental search MVP."""
from alembic import op
import sqlalchemy as sa

revision = "0007_whatsapp_rentals"
down_revision = "0006_job_skill_tags"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "rental_listings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("locality", sa.String(150), nullable=False),
        sa.Column("rent", sa.Integer(), nullable=False),
        sa.Column("bedrooms", sa.Integer(), nullable=False),
        sa.Column("furnishing", sa.String(50)),
        sa.Column("property_type", sa.String(80)),
        sa.Column("description", sa.Text()),
        sa.Column("listing_url", sa.String(1500)),
        sa.Column("contact_phone", sa.String(30)),
        sa.Column("contact_share_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_name", sa.String(100), nullable=False, server_default="owner"),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rental_listings_locality", "rental_listings", ["locality"])
    op.create_index("ix_rental_listings_rent", "rental_listings", ["rent"])
    op.create_index("ix_rental_listings_available", "rental_listings", ["available"])
    op.create_index("ix_rentals_available_locality_rent", "rental_listings", ["available", "locality", "rent"])
    op.create_table(
        "whatsapp_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone", sa.String(30), nullable=False, unique=True),
        sa.Column("state", sa.String(30), nullable=False, server_default="new"),
        sa.Column("preferences_json", sa.JSON(), nullable=False),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opted_out", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_whatsapp_users_phone", "whatsapp_users", ["phone"])

def downgrade():
    op.drop_index("ix_whatsapp_users_phone", table_name="whatsapp_users")
    op.drop_table("whatsapp_users")
    op.drop_index("ix_rentals_available_locality_rent", table_name="rental_listings")
    op.drop_index("ix_rental_listings_available", table_name="rental_listings")
    op.drop_index("ix_rental_listings_rent", table_name="rental_listings")
    op.drop_index("ix_rental_listings_locality", table_name="rental_listings")
    op.drop_table("rental_listings")
