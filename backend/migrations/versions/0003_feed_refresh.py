"""Track article extraction and persistent refresh schedules."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("ingestion_meta", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table("feed_states",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("lease_token", sa.String(36)), sa.Column("lease_until", sa.DateTime()),
        sa.Column("last_started_at", sa.DateTime()), sa.Column("last_finished_at", sa.DateTime()),
        sa.Column("next_refresh_at", sa.DateTime()),
        sa.Column("report", sa.JSON(), nullable=False), sa.Column("error", sa.Text()))


def downgrade():
    op.drop_table("feed_states")
    op.drop_column("documents", "ingestion_meta")
