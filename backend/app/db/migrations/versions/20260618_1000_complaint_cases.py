"""complaint_cases_table

Revision ID: 8b1e3f95c2d4
Revises: 6a0d2c84f1b3
Create Date: 2026-06-18 10:00:00.000000+00:00

Create complaint_cases table — previously only created by init_db() (SQLAlchemy Base),
not by Alembic migrations. This ensures fresh DB and old-initial DB upgrades both get the table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b1e3f95c2d4'
down_revision: Union[str, None] = '6a0d2c84f1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table: str) -> bool:
    dialect_name = conn.dialect.name
    if dialect_name == "sqlite":
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        ).fetchall()
        return len(rows) > 0
    else:
        from sqlalchemy import text
        result = conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :tbl"
            ),
            {"tbl": table},
        ).fetchone()
        return result is not None


def upgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "complaint_cases"):
        return

    op.create_table(
        "complaint_cases",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("province", sa.String(32), nullable=False, server_default="全国"),
        sa.Column("source_url", sa.String(512), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=True),
        sa.Column("project_number", sa.String(128), nullable=True),
        sa.Column("complainant", sa.Text, nullable=True),
        sa.Column("respondent", sa.Text, nullable=True),
        sa.Column("decision_date", sa.String(16), nullable=True),
        sa.Column("decision_type", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("complaint_types", sa.Text, nullable=True),
        sa.Column("legal_basis", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("raw_content", sa.Text, nullable=True),
        sa.Column("is_analyzed", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    if _table_exists(op.get_bind(), "complaint_cases"):
        op.drop_table("complaint_cases")
