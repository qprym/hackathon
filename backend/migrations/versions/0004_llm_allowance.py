"""Persist the shared LLM trial allowance across worker restarts and dates."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("llm_allowance",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("spent", sa.Float(), nullable=False))


def downgrade():
    op.drop_table("llm_allowance")
