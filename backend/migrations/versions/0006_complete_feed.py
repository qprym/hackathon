"""Feed snapshots and fenced renewable job leases."""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('runs',sa.Column('lease_token',sa.String(36),nullable=True))
    op.add_column('ranking_jobs',sa.Column('lease_token',sa.String(36),nullable=True))
    op.add_column('ranking_jobs',sa.Column('attempts',sa.Integer(),nullable=False,server_default='0'))
    op.create_table('feed_snapshots',
        sa.Column('id',sa.String(64),primary_key=True),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('company_id',sa.String(100),sa.ForeignKey('companies.id'),nullable=False),
        sa.Column('context_key',sa.String(64),nullable=False),
        sa.Column('query_key',sa.String(64),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('expires_at',sa.DateTime(),nullable=False))
    op.create_index('ix_feed_snapshots_user_id','feed_snapshots',['user_id'])
    op.create_index('ix_feed_snapshots_expires_at','feed_snapshots',['expires_at'])


def downgrade():
    op.drop_table('feed_snapshots')
    op.drop_column('ranking_jobs','attempts')
    op.drop_column('ranking_jobs','lease_token')
    op.drop_column('runs','lease_token')
