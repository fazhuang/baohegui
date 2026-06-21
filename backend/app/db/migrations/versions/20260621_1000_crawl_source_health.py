"""crawl_source_health table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-21

Phase 2 Block C — 持久化运行时来源健康状态：
  - crawl_source_health: 每个来源的运行统计和健康状态
  - 替代静态 canary_config.json fixture 文件作为运行时状态来源
  - 健康状态: collecting / not_enough_data / healthy / degraded / failed
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'crawl_source_health',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('source_name', sa.String(64), nullable=False),
        sa.Column('first_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_success_at', sa.DateTime(), nullable=True),
        sa.Column('consecutive_failures', sa.Integer(), server_default='0'),
        sa.Column('total_runs', sa.Integer(), server_default='0'),
        sa.Column('successful_runs', sa.Integer(), server_default='0'),
        sa.Column('fetched_count', sa.Integer(), server_default='0'),
        sa.Column('saved_count', sa.Integer(), server_default='0'),
        sa.Column('duplicate_count', sa.Integer(), server_default='0'),
        sa.Column('completeness_rate', sa.Float(), server_default='0.0'),
        sa.Column('last_error_type', sa.String(64), nullable=True),
        sa.Column('last_error_message', sa.Text(), nullable=True),
        sa.Column('health_status', sa.String(32), nullable=False, server_default='collecting'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_name', name='uq_crawl_source_health_source_name'),
    )
    op.create_index('ix_crawl_source_health_source_name', 'crawl_source_health', ['source_name'])
    op.create_index('ix_crawl_source_health_health_status', 'crawl_source_health', ['health_status'])


def downgrade() -> None:
    op.drop_index('ix_crawl_source_health_health_status', table_name='crawl_source_health')
    op.drop_index('ix_crawl_source_health_source_name', table_name='crawl_source_health')
    op.drop_table('crawl_source_health')
