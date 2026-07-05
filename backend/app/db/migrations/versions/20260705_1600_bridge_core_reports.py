"""bridge: core report tables for policy chain

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-05 16:00:00

桥接迁移：显式创建 Policy 决策链所依赖的基础表。
这些表此前由应用运行时 Base.metadata.create_all 隐式创建，
本迁移使全新数据库仅通过 Alembic 即可完整建库。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table_name: str) -> bool:
    insp = Inspector.from_engine(conn)
    return table_name in insp.get_table_names()


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    # ── uploaded_files ──
    if not _table_exists(conn, "uploaded_files"):
        op.create_table(
            "uploaded_files",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer, nullable=False),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("file_size", sa.Integer, nullable=False),
            sa.Column("file_hash", sa.String(64), nullable=False),
            sa.Column("page_count", sa.Integer, nullable=True),
            sa.Column("storage_path", sa.String(512), nullable=False),
            sa.Column("status",
                      sa.Enum("uploaded", "parsing", "queued", "checking", "completed", "failed",
                              name="file_status"),
                      server_default="uploaded"),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("failed_at", sa.DateTime, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )

    # ── document_sections ──
    if not _table_exists(conn, "document_sections"):
        op.create_table(
            "document_sections",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("file_id", sa.Integer, sa.ForeignKey("uploaded_files.id"), nullable=False),
            sa.Column("section_type", sa.String(64), nullable=False),
            sa.Column("section_number", sa.String(32), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("content", sa.Text, nullable=False),
            sa.Column("page_start", sa.Integer, nullable=True),
            sa.Column("page_end", sa.Integer, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )

    # ── compliance_reports ──
    if not _table_exists(conn, "compliance_reports"):
        if dialect == "sqlite":
            # SQLite: raw DDL with inline CHECK constraints
            conn.execute(sa.text("PRAGMA foreign_keys=ON"))
            conn.execute(sa.text("""
                CREATE TABLE compliance_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL REFERENCES uploaded_files(id),
                    total_score FLOAT NOT NULL,
                    section_score FLOAT,
                    keyword_score FLOAT,
                    forbidden_score FLOAT,
                    semantic_score FLOAT,
                    violation_count INTEGER DEFAULT 0,
                    report_data TEXT,
                    decision_action VARCHAR(32) CHECK(
                        decision_action IN ('pass', 'warn', 'require_review', 'block')
                        OR decision_action IS NULL
                    ),
                    decision_risk_level VARCHAR(16) CHECK(
                        decision_risk_level IN ('low', 'medium', 'high', 'critical')
                        OR decision_risk_level IS NULL
                    ),
                    decision_requires_human_review BOOLEAN,
                    decision_hash VARCHAR(64),
                    policy_schema_version VARCHAR(16),
                    decision_integrity_status VARCHAR(32) DEFAULT 'legacy_unverifiable' CHECK(
                        decision_integrity_status IN ('verified', 'legacy_unverifiable', 'integrity_failed')
                        OR decision_integrity_status IS NULL
                    ),
                    report_pdf_path VARCHAR(512),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    checked_by INTEGER
                )
            """))
        else:
            # PostgreSQL: use Alembic API with CheckConstraint in the column definitions
            op.create_table(
                "compliance_reports",
                sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
                sa.Column("file_id", sa.Integer, sa.ForeignKey("uploaded_files.id"), nullable=False),
                sa.Column("total_score", sa.Float, nullable=False),
                sa.Column("section_score", sa.Float, nullable=True),
                sa.Column("keyword_score", sa.Float, nullable=True),
                sa.Column("forbidden_score", sa.Float, nullable=True),
                sa.Column("semantic_score", sa.Float, nullable=True),
                sa.Column("violation_count", sa.Integer, server_default="0"),
                sa.Column("report_data", sa.Text, nullable=True),
                sa.Column("decision_action", sa.String(32), nullable=True),
                sa.Column("decision_risk_level", sa.String(16), nullable=True),
                sa.Column("decision_requires_human_review", sa.Boolean(), nullable=True),
                sa.Column("decision_hash", sa.String(64), nullable=True),
                sa.Column("policy_schema_version", sa.String(16), nullable=True),
                sa.Column("decision_integrity_status", sa.String(32), nullable=True,
                          server_default="legacy_unverifiable"),
                sa.Column("report_pdf_path", sa.String(512), nullable=True),
                sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
                sa.Column("checked_by", sa.Integer, nullable=True),
            )
            # Postgres: add CHECK after creation
            for ck_name, ck_cond in [
                ("ck_decision_action",
                 "decision_action IN ('pass', 'warn', 'require_review', 'block') OR decision_action IS NULL"),
                ("ck_decision_risk_level",
                 "decision_risk_level IN ('low', 'medium', 'high', 'critical') OR decision_risk_level IS NULL"),
                ("ck_decision_integrity_status",
                 "decision_integrity_status IN ('verified', 'legacy_unverifiable', 'integrity_failed') OR decision_integrity_status IS NULL"),
            ]:
                try:
                    op.create_check_constraint(ck_name, "compliance_reports", ck_cond)
                except Exception:
                    pass


def downgrade() -> None:
    conn = op.get_bind()
    for table in ["compliance_reports", "document_sections", "uploaded_files"]:
        if _table_exists(conn, table):
            op.drop_table(table)
