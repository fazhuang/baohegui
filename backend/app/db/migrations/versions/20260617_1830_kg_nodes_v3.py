"""kg_nodes_v3_columns

Revision ID: 6a0d2c84f1b3
Revises: 3f5829544a0c
Create Date: 2026-06-17 18:30:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a0d2c84f1b3'
down_revision: Union[str, None] = '3f5829544a0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 添加 v3 字段 — 使用 raw SQL 以兼容 SQLite 和 PostgreSQL
    op.add_column('kg_nodes', sa.Column('source_url', sa.String(1024), server_default='', nullable=True))
    op.add_column('kg_nodes', sa.Column('rule_id', sa.String(64), server_default=None, nullable=True))
    op.add_column('kg_nodes', sa.Column('jurisdiction', sa.String(128), server_default='', nullable=True))
    op.add_column('kg_nodes', sa.Column('effective_date', sa.Date, server_default=None, nullable=True))
    op.add_column('kg_nodes', sa.Column('publish_date', sa.Date, server_default=None, nullable=True))
    op.add_column('kg_nodes', sa.Column('metadata_json', sa.Text, server_default='{}', nullable=True))

    # 创建复合索引
    try:
        op.create_index('ix_kg_nodes_type_status', 'kg_nodes', ['node_type', 'audit_status'])
    except Exception:
        pass
    try:
        op.create_index('ix_kg_nodes_type_trust', 'kg_nodes', ['node_type', 'trust_level'])
    except Exception:
        pass
    try:
        op.create_index('ix_kg_nodes_rule_id', 'kg_nodes', ['rule_id'])
    except Exception:
        pass


def downgrade() -> None:
    op.drop_index('ix_kg_nodes_rule_id', table_name='kg_nodes')
    op.drop_index('ix_kg_nodes_type_trust', table_name='kg_nodes')
    op.drop_index('ix_kg_nodes_type_status', table_name='kg_nodes')
    op.drop_column('kg_nodes', 'metadata_json')
    op.drop_column('kg_nodes', 'publish_date')
    op.drop_column('kg_nodes', 'effective_date')
    op.drop_column('kg_nodes', 'jurisdiction')
    op.drop_column('kg_nodes', 'rule_id')
    op.drop_column('kg_nodes', 'source_url')
