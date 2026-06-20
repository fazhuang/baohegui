"""crawl_jobs + crawl_job_items

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-20

Phase 2 — 采集任务持久化：
  - crawl_jobs: 每次采集任务主记录
  - crawl_job_items: 每个采集源的明细结果
  替代 sync_scheduler 的 in-memory _history / _case_history。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'crawl_jobs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_type', sa.String(32), nullable=False, server_default='case_scrape'),
        sa.Column('status', sa.String(16), nullable=False, server_default='running'),
        sa.Column('trigger_type', sa.String(16), nullable=False, server_default='manual'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('total_sources', sa.Integer(), server_default='0'),
        sa.Column('successful_sources', sa.Integer(), server_default='0'),
        sa.Column('failed_sources', sa.Integer(), server_default='0'),
        sa.Column('total_fetched', sa.Integer(), server_default='0'),
        sa.Column('total_saved', sa.Integer(), server_default='0'),
        sa.Column('total_duplicates', sa.Integer(), server_default='0'),
        sa.Column('totals_json', sa.Text(), nullable=True),
        sa.Column('kg_synced', sa.Integer(), server_default='0'),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_crawl_jobs_status', 'crawl_jobs', ['status'])
    op.create_index('ix_crawl_jobs_created_at', 'crawl_jobs', ['created_at'])

    op.create_table(
        'crawl_job_items',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('source_name', sa.String(64), nullable=False),
        sa.Column('source_type', sa.String(32), nullable=False, server_default='http'),
        sa.Column('status', sa.String(16), nullable=False, server_default='running'),
        sa.Column('fetched_count', sa.Integer(), server_default='0'),
        sa.Column('saved_count', sa.Integer(), server_default='0'),
        sa.Column('duplicate_count', sa.Integer(), server_default='0'),
        sa.Column('error_type', sa.String(64), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_crawl_job_items_job_id', 'crawl_job_items', ['job_id'])
    op.create_index('ix_crawl_job_items_source_name', 'crawl_job_items', ['source_name'])


def downgrade() -> None:
    op.drop_index('ix_crawl_job_items_source_name', table_name='crawl_job_items')
    op.drop_index('ix_crawl_job_items_job_id', table_name='crawl_job_items')
    op.drop_table('crawl_job_items')
    op.drop_index('ix_crawl_jobs_created_at', table_name='crawl_jobs')
    op.drop_index('ix_crawl_jobs_status', table_name='crawl_jobs')
    op.drop_table('crawl_jobs')
