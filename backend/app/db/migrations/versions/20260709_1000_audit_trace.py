"""add audit_trace for deterministic replay

Revision ID: 20260709_1000_audit_trace
Revises: 20260707_1400_policy_quarantine
Create Date: 2026-07-09 00:00:00

Adds audit_trace (JSONB) and audit_trace_valid (Boolean) columns
to compliance_reports for deterministic end-to-end replay verification.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260709_1000_audit_trace"
down_revision = "20260707_1400_policy_quarantine"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table (cross-dialect).

    Uses Inspector when available, falls back to SQLite PRAGMA.
    """
    from sqlalchemy.engine.reflection import Inspector
    from sqlalchemy import inspect

    conn = op.get_bind()
    try:
        inspector: Inspector = inspect(conn)
        columns = [c["name"] for c in inspector.get_columns(table_name)]
        return column_name in columns
    except Exception:
        # SQLite fallback
        try:
            result = conn.execute(
                sa.text(f"PRAGMA table_info({table_name})")
            )
            return any(row[1] == column_name for row in result)
        except Exception:
            return False


def upgrade():
    # Add audit_trace column (JSONB on PostgreSQL, JSON on SQLite)
    if not _column_exists("compliance_reports", "audit_trace"):
        with op.batch_alter_table("compliance_reports") as batch_op:
            batch_op.add_column(
                sa.Column("audit_trace", sa.JSON(), nullable=True)
            )

    # Add audit_trace_valid column
    if not _column_exists("compliance_reports", "audit_trace_valid"):
        with op.batch_alter_table("compliance_reports") as batch_op:
            batch_op.add_column(
                sa.Column("audit_trace_valid", sa.Boolean(), nullable=True)
            )

    # Existing reports without audit_trace remain legacy_unverifiable
    # — no backfill needed: decision_integrity_status already marks them.


def downgrade():
    # Drop audit_trace_valid
    if _column_exists("compliance_reports", "audit_trace_valid"):
        with op.batch_alter_table("compliance_reports") as batch_op:
            batch_op.drop_column("audit_trace_valid")

    # Drop audit_trace
    if _column_exists("compliance_reports", "audit_trace"):
        with op.batch_alter_table("compliance_reports") as batch_op:
            batch_op.drop_column("audit_trace")
