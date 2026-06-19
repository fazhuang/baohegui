"""add_complaint_cases_indexes

Revision ID: 9c2f4e06d5e8
Revises: 8b1e3f95c2d4
Create Date: 2026-06-19

Add performance indexes on complaint_cases:
  - ix_complaint_cases_source_url (UNIQUE) — 去重查询加速
  - ix_complaint_cases_decision_type — 按决定类型统计/筛选
  - ix_complaint_cases_province — 按省份筛选
  - ix_complaint_cases_is_analyzed — 规则矿机扫描
  - ix_complaint_cases_created_at — 按时间排序

All indexes are created with IF NOT EXISTS for idempotency.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c2f4e06d5e8'
down_revision: Union[str, None] = '8b1e3f95c2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_connection():
    """Get a connection from op.get_bind() — handles both Engine and Connection."""
    bind = op.get_bind()
    # SA 2.x: Engine no longer has .execute() directly; use .connect()
    if hasattr(bind, 'connect'):
        return bind.connect()
    return bind


def _index_exists(conn, index_name: str, table_name: str) -> bool:
    """Check if index exists (SQLite + PostgreSQL compatible)."""
    dialect = conn.dialect.name
    if dialect == "sqlite":
        result = conn.exec_driver_sql(
            f"SELECT 1 FROM sqlite_master WHERE type='index' AND name='{index_name}'"
        )
        return result.fetchone() is not None
    else:
        # PostgreSQL
        result = conn.exec_driver_sql(
            f"SELECT 1 FROM pg_indexes WHERE indexname = '{index_name}'"
        )
        return result.fetchone() is not None


def upgrade() -> None:
    """Add indexes; idempotent — skips if already present."""
    conn = _get_connection()
    try:
        _create_index(conn, "ix_complaint_cases_source_url", "complaint_cases", ["source_url"], unique=True)
        _create_index(conn, "ix_complaint_cases_decision_type", "complaint_cases", ["decision_type"])
        _create_index(conn, "ix_complaint_cases_province", "complaint_cases", ["province"])
        _create_index(conn, "ix_complaint_cases_is_analyzed", "complaint_cases", ["is_analyzed"])
        _create_index(conn, "ix_complaint_cases_created_at", "complaint_cases", ["created_at"])
    finally:
        if conn is not bind_fallback():
            conn.close()


def bind_fallback():
    """Return the current bind for checking if conn is a temporary connect()."""
    bind = op.get_bind()
    if hasattr(bind, 'connect'):
        return None  # Engine — conn was a temporary .connect()
    return bind  # Connection — conn IS the bind


def _create_index(conn, index_name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    """Create index if it doesn't exist."""
    if _index_exists(conn, index_name, table_name):
        return
    col_str = ", ".join(columns)
    unique_str = "UNIQUE " if unique else ""
    conn.exec_driver_sql(
        f"CREATE {unique_str}INDEX {index_name} ON {table_name} ({col_str})"
    )


def downgrade() -> None:
    """Drop indexes."""
    op.drop_index("ix_complaint_cases_source_url", table_name="complaint_cases")
    op.drop_index("ix_complaint_cases_decision_type", table_name="complaint_cases")
    op.drop_index("ix_complaint_cases_province", table_name="complaint_cases")
    op.drop_index("ix_complaint_cases_is_analyzed", table_name="complaint_cases")
    op.drop_index("ix_complaint_cases_created_at", table_name="complaint_cases")
