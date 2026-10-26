"""Auditable neural relevance jobs and cache."""
from alembic import op
import sqlalchemy as sa

revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('ranking_jobs',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('company_id',sa.String(100),sa.ForeignKey('companies.id'),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),sa.Column('cache_keys',sa.JSON(),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),sa.Column('response',sa.JSON()),sa.Column('error',sa.Text()),
        sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('finished_at',sa.DateTime()),sa.Column('lease_until',sa.DateTime()))
    op.create_index('ix_ranking_jobs_status','ranking_jobs',['status'])
    op.create_table('relevance_assessments',
        sa.Column('cache_key',sa.String(64),primary_key=True),sa.Column('article_key',sa.String(64),nullable=False),
        sa.Column('context_key',sa.String(64),nullable=False),
        sa.Column('company_id',sa.String(100),sa.ForeignKey('companies.id'),nullable=False),
        sa.Column('model_id',sa.String(150),nullable=False),sa.Column('version',sa.String(80),nullable=False),
        sa.Column('job_id',sa.String(36),sa.ForeignKey('ranking_jobs.id'),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),sa.Column('result',sa.JSON()),sa.Column('error',sa.Text()),
        sa.Column('created_at',sa.DateTime(),nullable=False))
    for name in ('article_key','context_key','company_id'):
        op.create_index('ix_relevance_assessments_'+name,'relevance_assessments',[name])

def downgrade():
    op.drop_table('relevance_assessments')
    op.drop_table('ranking_jobs')
