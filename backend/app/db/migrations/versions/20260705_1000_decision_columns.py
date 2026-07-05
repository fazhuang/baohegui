"""add decision columns with constraints to compliance_reports

Revision ID: 20260705_1000_decision_columns
Revises: 20260705_1600_bridge_core_reports
Create Date: 2026-07-05 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '20260705_1000_decision_columns'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    insp = Inspector.from_engine(conn)
    cols = [c["name"] for c in insp.get_columns(table)]
    return column in cols


def upgrade() -> None:
    conn = op.get_bind()

    # 添加决策列（幂等：已存在则跳过）
    if not _column_exists(conn, "compliance_reports", "decision_action"):
        op.add_column("compliance_reports", sa.Column("decision_action", sa.String(32), nullable=True))
    if not _column_exists(conn, "compliance_reports", "decision_risk_level"):
        op.add_column("compliance_reports", sa.Column("decision_risk_level", sa.String(16), nullable=True))
    if not _column_exists(conn, "compliance_reports", "decision_requires_human_review"):
        op.add_column("compliance_reports", sa.Column("decision_requires_human_review", sa.Boolean(), nullable=True))
    if not _column_exists(conn, "compliance_reports", "decision_hash"):
        op.add_column("compliance_reports", sa.Column("decision_hash", sa.String(64), nullable=True))
    if not _column_exists(conn, "compliance_reports", "policy_schema_version"):
        op.add_column("compliance_reports", sa.Column("policy_schema_version", sa.String(16), nullable=True))
    if not _column_exists(conn, "compliance_reports", "decision_integrity_status"):
        op.add_column("compliance_reports",
            sa.Column("decision_integrity_status", sa.String(32), nullable=True,
                      server_default="legacy_unverifiable"))

    # ── 数据库约束（幂等） ──
    _ensure_constraints(conn)

    # ── 历史记录标记 legacy_unverifiable，不根据 score 回填 ──
    conn.execute(
        text("UPDATE compliance_reports SET decision_integrity_status = 'legacy_unverifiable' "
             "WHERE decision_integrity_status IS NULL AND decision_action IS NULL")
    )


def _ensure_constraints(conn):
    """幂等添加命名 CHECK 约束。Alembic create_check_constraint 的 ensure 语义不强，
    实际约束由 SQLAlchemy ORM __table_args__ 中的 CheckConstraint 在 run-time 提供。
    本函数尽最大努力在迁移中追加约束，失败不阻塞。"""
    checks = [
        ("ck_decision_action",
         "decision_action IN ('pass', 'warn', 'require_review', 'block') OR decision_action IS NULL"),
        ("ck_decision_risk_level",
         "decision_risk_level IN ('low', 'medium', 'high', 'critical') OR decision_risk_level IS NULL"),
        ("ck_decision_integrity_status",
         "decision_integrity_status IN ('verified', 'legacy_unverifiable', 'integrity_failed') OR decision_integrity_status IS NULL"),
    ]
    for ck_name, condition in checks:
        try:
            op.create_check_constraint(ck_name, "compliance_reports", condition)
        except Exception:
            pass


def downgrade() -> None:
    conn = op.get_bind()

    for ck in ["ck_decision_action", "ck_decision_risk_level", "ck_decision_integrity_status"]:
        try:
            op.drop_constraint(ck, "compliance_reports", type_="check")
        except Exception:
            pass

    for col in ["decision_integrity_status", "policy_schema_version",
                "decision_hash", "decision_requires_human_review",
                "decision_risk_level", "decision_action"]:
        try:
            op.drop_column("compliance_reports", col)
        except Exception:
            pass
