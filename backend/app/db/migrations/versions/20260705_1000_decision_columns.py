"""add decision columns to compliance_reports

Revision ID: 20260705_1000_decision_columns
Revises: 20260621_1100_daily_health_snapshot
Create Date: 2026-07-05 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260705_1000_decision_columns'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('compliance_reports', sa.Column('decision_action', sa.String(32), nullable=True))
    op.add_column('compliance_reports', sa.Column('decision_risk_level', sa.String(16), nullable=True))
    op.add_column('compliance_reports', sa.Column('decision_requires_human_review', sa.Integer(), nullable=True))
    op.add_column('compliance_reports', sa.Column('decision_hash', sa.String(64), nullable=True))
    op.add_column('compliance_reports', sa.Column('policy_schema_version', sa.String(16), nullable=True))
    op.add_column('compliance_reports', sa.Column('decision_integrity_status', sa.String(32), nullable=True,
                                                   server_default='legacy_unverifiable'))

    # 历史记录标记 legacy_unverifiable，不根据 total_score 回填
    # 新报告将由应用层写入权威决策值


def downgrade() -> None:
    op.drop_column('compliance_reports', 'decision_integrity_status')
    op.drop_column('compliance_reports', 'policy_schema_version')
    op.drop_column('compliance_reports', 'decision_hash')
    op.drop_column('compliance_reports', 'decision_requires_human_review')
    op.drop_column('compliance_reports', 'decision_risk_level')
    op.drop_column('compliance_reports', 'decision_action')
