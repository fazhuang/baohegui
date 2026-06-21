"""add daily_health_snapshots + crawl_source_health extended columns

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-21

Phase 2 re-audit:
  - daily_health_snapshots: 每个来源每天的运行记录（准确判断连续 N 天）
  - crawl_source_health 新增字段:
    * last_status — 最近一次运行状态 (success/partial/failed)
    * last_success_date — 最近成功日期
    * consecutive_success_days — 连续成功天数
    * observed_days — 实际有效观测天数
    * (completeness_rate 保持不变)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── daily_health_snapshots 表 ───────────────────
    op.create_table(
        'daily_health_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('source_name', sa.String(64), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='success'),
        sa.Column('runs', sa.Integer(), server_default='0'),
        sa.Column('fetched', sa.Integer(), server_default='0'),
        sa.Column('saved', sa.Integer(), server_default='0'),
        sa.Column('completeness', sa.Float(), server_default='0.0'),
        sa.Column('error_type', sa.String(64), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'source_name', 'snapshot_date',
            name='uq_daily_snapshot_source_date',
        ),
    )
    op.create_index('ix_daily_snapshots_source_name', 'daily_health_snapshots', ['source_name'])
    op.create_index('ix_daily_snapshots_date', 'daily_health_snapshots', ['snapshot_date'])

    # ── crawl_source_health 新增列（幂等）────────────
    for col_name, col_type, col_kwargs in [
        ('last_status', sa.String(16), {'nullable': True}),
        ('last_success_date', sa.Date(), {'nullable': True}),
        ('consecutive_success_days', sa.Integer(), {'server_default': '0'}),
        ('observed_days', sa.Integer(), {'server_default': '0'}),
    ]:
        try:
            op.add_column('crawl_source_health', sa.Column(col_name, col_type, **col_kwargs))
        except Exception:
            pass  # 列已存在（幂等）


def downgrade() -> None:
    # 移除 crawl_source_health 新列
    for col_name in ['last_status', 'last_success_date', 'consecutive_success_days', 'observed_days']:
        try:
            op.drop_column('crawl_source_health', col_name)
        except Exception:
            pass

    # 移除 daily_health_snapshots 表
    op.drop_index('ix_daily_snapshots_date', table_name='daily_health_snapshots')
    op.drop_index('ix_daily_snapshots_source_name', table_name='daily_health_snapshots')
    op.drop_table('daily_health_snapshots')
