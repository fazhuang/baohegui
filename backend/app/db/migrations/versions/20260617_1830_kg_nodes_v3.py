"""kg_nodes_v3_columns

Revision ID: 6a0d2c84f1b3
Revises: 3f5829544a0c
Create Date: 2026-06-17 18:30:00.000000+00:00

Note: This migration is safe whether or not the initial migration already created
these columns. It checks for column existence before adding (SQLite) or uses
IF NOT EXISTS (PostgreSQL). Indexes use IF NOT EXISTS / try/except guards.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a0d2c84f1b3'
down_revision: Union[str, None] = '3f5829544a0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists in the given table."""
    dialect_name = conn.dialect.name
    if dialect_name == "sqlite":
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        return any(row[1] == column for row in rows)
    else:
        # PostgreSQL
        from sqlalchemy import text
        result = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :tbl AND column_name = :col"
            ),
            {"tbl": table, "col": column},
        ).fetchone()
        return result is not None


def _index_exists(conn, index_name: str) -> bool:
    """Check if an index exists."""
    dialect_name = conn.dialect.name
    if dialect_name == "sqlite":
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index' AND name = ?",
            (index_name,),
        ).fetchall()
        return len(rows) > 0
    else:
        from sqlalchemy import text
        result = conn.execute(
            text(
                "SELECT 1 FROM pg_indexes WHERE indexname = :idx"
            ),
            {"idx": index_name},
        ).fetchone()
        return result is not None


def _table_exists(conn, table: str) -> bool:
    """Check if a table exists."""
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


def _safe_add_column(conn, table: str, column_name: str, column_spec) -> None:
    """Add a column only if it doesn't already exist AND the table exists."""
    if not _table_exists(conn, table):
        return
    if not _column_exists(conn, table, column_name):
        op.add_column(table, column_spec)


def _safe_create_index(index_name: str, table: str, columns: list) -> None:
    """Create an index only if it doesn't already exist AND the table exists."""
    try:
        conn = op.get_bind()
        if not _table_exists(conn, table):
            return
        if not _index_exists(conn, index_name):
            op.create_index(index_name, table, columns)
    except Exception:
        pass


def _safe_create_nodes_table(conn) -> None:
    """Create kg_nodes table if it doesn't exist (for old DBs that never had it)."""
    if _table_exists(conn, "kg_nodes"):
        return
    dialect_name = conn.dialect.name
    if dialect_name == "sqlite":
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS kg_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_type VARCHAR(32) NOT NULL,
                title VARCHAR(512) NOT NULL,
                content TEXT NOT NULL,
                source VARCHAR(256) DEFAULT '',
                source_url VARCHAR(1024) DEFAULT '',
                tags VARCHAR(512) DEFAULT '',
                rule_id VARCHAR(64),
                jurisdiction VARCHAR(128) DEFAULT '',
                effective_date DATE,
                publish_date DATE,
                metadata_json TEXT DEFAULT '{}',
                trust_level FLOAT NOT NULL DEFAULT 0.5,
                audit_status VARCHAR(16) NOT NULL DEFAULT 'unreviewed',
                audited_by INTEGER,
                audited_at DATETIME,
                created_at DATETIME
            )
        """)
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    else:
        op.create_table(
            "kg_nodes",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("node_type", sa.String(32), nullable=False),
            sa.Column("title", sa.String(512), nullable=False),
            sa.Column("content", sa.Text, nullable=False),
            sa.Column("source", sa.String(256), server_default=""),
            sa.Column("source_url", sa.String(1024), server_default=""),
            sa.Column("tags", sa.String(512), server_default=""),
            sa.Column("rule_id", sa.String(64), nullable=True),
            sa.Column("jurisdiction", sa.String(128), server_default=""),
            sa.Column("effective_date", sa.Date, nullable=True),
            sa.Column("publish_date", sa.Date, nullable=True),
            sa.Column("metadata_json", sa.Text, server_default="{}"),
            sa.Column("trust_level", sa.Float, nullable=False, server_default="0.5"),
            sa.Column("audit_status", sa.String(16), nullable=False, server_default="unreviewed"),
            sa.Column("audited_by", sa.Integer, nullable=True),
            sa.Column("audited_at", sa.DateTime, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )


def upgrade() -> None:
    conn = op.get_bind()

    # ── Phase 1 fix: ensure tables exist before trying to add columns ──
    # Old DBs whose initial migration was empty will have alembic_version = 3f5829544a0c
    # but no kg_nodes / kg_edges tables. Create them with full v3 schema.
    _safe_create_nodes_table(conn)
    _safe_create_edges_table(conn)

    # Column specs — add only if missing (safe for fresh DB + upgrade)
    _safe_add_column(conn, 'kg_nodes', 'source_url',
                     sa.Column('source_url', sa.String(1024), server_default='', nullable=True))
    _safe_add_column(conn, 'kg_nodes', 'rule_id',
                     sa.Column('rule_id', sa.String(64), server_default=None, nullable=True))
    _safe_add_column(conn, 'kg_nodes', 'jurisdiction',
                     sa.Column('jurisdiction', sa.String(128), server_default='', nullable=True))
    _safe_add_column(conn, 'kg_nodes', 'effective_date',
                     sa.Column('effective_date', sa.Date, server_default=None, nullable=True))
    _safe_add_column(conn, 'kg_nodes', 'publish_date',
                     sa.Column('publish_date', sa.Date, server_default=None, nullable=True))
    _safe_add_column(conn, 'kg_nodes', 'metadata_json',
                     sa.Column('metadata_json', sa.Text, server_default='{}', nullable=True))
    _safe_add_column(conn, 'kg_nodes', 'trust_level',
                     sa.Column('trust_level', sa.Float, server_default='0.5', nullable=True))
    _safe_add_column(conn, 'kg_nodes', 'audit_status',
                     sa.Column('audit_status', sa.String(16), server_default='unreviewed', nullable=True))
    _safe_add_column(conn, 'kg_nodes', 'audited_by',
                     sa.Column('audited_by', sa.Integer, server_default=None, nullable=True))
    _safe_add_column(conn, 'kg_nodes', 'audited_at',
                     sa.Column('audited_at', sa.DateTime, server_default=None, nullable=True))
    _safe_add_column(conn, 'kg_nodes', 'tags',
                     sa.Column('tags', sa.String(512), server_default='', nullable=True))
    _safe_add_column(conn, 'kg_nodes', 'source',
                     sa.Column('source', sa.String(256), server_default='', nullable=True))

    # Create indexes safely
    _safe_create_index('ix_kg_nodes_rule_id', 'kg_nodes', ['rule_id'])
    _safe_create_index('ix_kg_nodes_type_status', 'kg_nodes', ['node_type', 'audit_status'])
    _safe_create_index('ix_kg_nodes_type_trust', 'kg_nodes', ['node_type', 'trust_level'])
    _safe_create_index('ix_kg_nodes_trust_level', 'kg_nodes', ['trust_level'])
    _safe_create_index('ix_kg_nodes_audit_status', 'kg_nodes', ['audit_status'])

    # Ensure kg_edges exists (may have been created by fixed initial migration)
    _safe_create_edges_table(conn)
def _safe_create_edges_table(conn) -> None:
    """Create kg_edges if it doesn't exist."""
    dialect_name = conn.dialect.name
    if dialect_name == "sqlite":
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='kg_edges'"
        ).fetchall()
        if not rows:
            conn.exec_driver_sql("""
                CREATE TABLE IF NOT EXISTS kg_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL REFERENCES kg_nodes(id),
                    target_id INTEGER NOT NULL REFERENCES kg_nodes(id),
                    relation VARCHAR(64) NOT NULL,
                    weight FLOAT DEFAULT 1.0,
                    created_at DATETIME
                )
            """)
    else:
        from sqlalchemy import text
        result = conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'kg_edges'"
            )
        ).fetchone()
        if not result:
            op.create_table(
                "kg_edges",
                sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
                sa.Column("source_id", sa.Integer, sa.ForeignKey("kg_nodes.id"), nullable=False),
                sa.Column("target_id", sa.Integer, sa.ForeignKey("kg_nodes.id"), nullable=False),
                sa.Column("relation", sa.String(64), nullable=False),
                sa.Column("weight", sa.Float, server_default="1.0"),
                sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
            )


def downgrade() -> None:
    """Downgrade is NOT guaranteed to be clean:
    - Columns may already exist from initial schema → skipping column drops is safe.
    - Indexes are dropped if they exist.
    - kg_edges is preserved (may also be in initial schema).
    """
    # Only drop indexes; don't drop columns since the fixed initial migration
    # also creates them — a downgrade of this migration should just unwind
    # what this specific migration adds. Since columns are if-exists, reverse
    # is also if-exists.
    for idx_name, tbl in [
        ("ix_kg_nodes_rule_id", "kg_nodes"),
        ("ix_kg_nodes_type_status", "kg_nodes"),
        ("ix_kg_nodes_type_trust", "kg_nodes"),
        ("ix_kg_nodes_trust_level", "kg_nodes"),
        ("ix_kg_nodes_audit_status", "kg_nodes"),
    ]:
        try:
            if _index_exists(op.get_bind(), idx_name):
                op.drop_index(idx_name, table_name=tbl)
        except Exception:
            pass
