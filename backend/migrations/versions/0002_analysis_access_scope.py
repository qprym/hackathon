"""Capture the company permissions used to produce an analysis."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("runs", sa.Column("access_scope", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    op.drop_column("runs", "access_scope")
