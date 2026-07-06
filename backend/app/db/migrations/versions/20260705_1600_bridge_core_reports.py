"""bridge: core report tables for policy chain

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-05 16:00:00

桥接迁移：显式创建 Policy 决策链所依赖的基础表。
这些表此前由应用运行时 Base.metadata.create_all 隐式创建，
本迁移使全新数据库仅通过 Alembic 即可完整建库。

迁移所有权：本迁移使用 _bhg_migration_objects 表记录自己创建的表。
downgrade 只删除登记了所有权的表，不会删除升级前已存在的用户数据表。
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


_OWNERSHIP_TABLE = "_bhg_migration_objects"

# FK-safe drop order: children before parents.
# downgrade must iterate this list in order so FK dependencies are respected.
_DROP_ORDER = (
    "compliance_reports",
    "document_sections",
    "uploaded_files",
)


def _table_exists(conn, table_name: str) -> bool:
    insp = Inspector.from_engine(conn)
    return table_name in insp.get_table_names()


def _ensure_ownership_table(conn):
    """Create the ownership tracking table if it doesn't exist.

    Returns True when this call actually created the table (so the caller
    knows this migration owns it).  Returns False when the table already
    existed.
    """
    if _table_exists(conn, _OWNERSHIP_TABLE):
        return False
    op.create_table(
        _OWNERSHIP_TABLE,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_name", sa.String(256), nullable=False),
        sa.Column("created_by_migration", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    # Index for fast lookups by revision
    op.create_index(f"ix_{_OWNERSHIP_TABLE}_revision", _OWNERSHIP_TABLE, ["revision"])
    return True


def _compute_drop_order(conn) -> list[str]:
    """Return the FK-safe ordered list of tables owned by this migration.

    Reads the ownership table and returns only entries that appear in
    _DROP_ORDER, in the fixed _DROP_ORDER sequence.  Unknown owned
    objects (tables not in _DROP_ORDER) are logged and skipped — they
    should not be silently dropped.
    """
    rows = conn.execute(
        sa.text(
            f"SELECT object_name FROM {_OWNERSHIP_TABLE} "
            f"WHERE revision = :rev AND object_type = 'table' AND created_by_migration = true"
        ),
        {"rev": revision},
    ).fetchall()

    owned = {row[0] for row in rows}
    ordered = [t for t in _DROP_ORDER if t in owned]
    unknown = owned - set(_DROP_ORDER)
    if unknown:
        import warnings
        warnings.warn(
            f"Migration {revision}: unknown owned objects not in drop order, skipping: {sorted(unknown)}"
        )
    return ordered


def _record_ownership(conn, object_type: str, object_name: str):
    """Record that this migration created an object."""
    conn.execute(
        sa.text(
            f"INSERT INTO {_OWNERSHIP_TABLE} (revision, object_type, object_name, created_by_migration) "
            f"VALUES (:rev, :otype, :oname, :flag)"
        ),
        {"rev": revision, "otype": object_type, "oname": object_name, "flag": True},
    )


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    # Ensure ownership tracking table exists first
    created_ownership_table = _ensure_ownership_table(conn)

    # ── uploaded_files ──
    created_uploaded = False
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
        created_uploaded = True

    # ── document_sections ──
    created_sections = False
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
        created_sections = True

    # ── compliance_reports ──
    created_reports = False
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
            # PostgreSQL: use Alembic API
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
            # Postgres: add CHECK constraints after creation (cannot fail silently)
            for ck_name, ck_cond in [
                ("ck_decision_action",
                 "decision_action IN ('pass', 'warn', 'require_review', 'block') OR decision_action IS NULL"),
                ("ck_decision_risk_level",
                 "decision_risk_level IN ('low', 'medium', 'high', 'critical') OR decision_risk_level IS NULL"),
                ("ck_decision_integrity_status",
                 "decision_integrity_status IN ('verified', 'legacy_unverifiable', 'integrity_failed') OR decision_integrity_status IS NULL"),
            ]:
                op.create_check_constraint(ck_name, "compliance_reports", ck_cond)
        created_reports = True

    # ── Record ownership for tables this migration actually created ──
    # Record in FK-dependency order (children first, parents last) so
    # downgrade can iterate in order without FK violations.
    if created_reports:
        _record_ownership(conn, "table", "compliance_reports")
    if created_sections:
        _record_ownership(conn, "table", "document_sections")
    if created_uploaded:
        _record_ownership(conn, "table", "uploaded_files")
    # Record self-ownership: only if this migration created the ownership table
    if created_ownership_table:
        _record_ownership(conn, "table", _OWNERSHIP_TABLE)


def downgrade() -> None:
    conn = op.get_bind()

    # Only drop tables that this migration actually created.
    # Tables that existed before the upgrade have no ownership record
    # and must not be touched.
    if _table_exists(conn, _OWNERSHIP_TABLE):
        owned = _compute_drop_order(conn)

        for table_name in owned:
            if _table_exists(conn, table_name):
                op.drop_table(table_name)

        # Check whether this migration owns the ownership table *before*
        # deleting the ownership records — once the records are gone we
        # can't tell anymore.
        owns_ownership_table = 0 < conn.execute(
            sa.text(
                f"SELECT COUNT(*) FROM {_OWNERSHIP_TABLE} "
                f"WHERE object_type = 'table' AND object_name = :otname AND created_by_migration = true"
            ),
            {"otname": _OWNERSHIP_TABLE},
        ).scalar()

        # Clean up ownership records for this revision
        conn.execute(
            sa.text(
                f"DELETE FROM {_OWNERSHIP_TABLE} WHERE revision = :rev"
            ),
            {"rev": revision},
        )

        # Clean up the ownership table itself only if this migration created it
        # *and* no rows remain after cleanup.
        if owns_ownership_table and _table_exists(conn, _OWNERSHIP_TABLE):
            remaining = conn.execute(
                sa.text(f"SELECT COUNT(*) FROM {_OWNERSHIP_TABLE}")
            ).scalar()
            if remaining == 0:
                op.drop_table(_OWNERSHIP_TABLE)
