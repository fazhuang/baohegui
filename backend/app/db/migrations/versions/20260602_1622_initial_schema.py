"""initial_schema

Revision ID: 3f5829544a0c
Revises:
Create Date: 2026-06-02 16:22:27.158867+00:00

Note: This migration now creates all tables including kg_nodes + kg_edges with full v3 schema.
The v3 migration (6a0d2c84f1b3) is a no-op when upgrading from this point, but still adds
columns for databases that were created before this migration was fixed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f5829544a0c'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables including kg_nodes and kg_edges with full schema."""
    # ── All model tables are auto-created via init_db() in production ──
    # This migration ensures fresh DBs get the complete schema via alembic.
    # Tables that already exist are skipped (IF NOT EXISTS via dialect).
    # We use raw SQL for safety — Alembic's create_table may not detect
    # IF NOT EXISTS-style guards.

    conn = op.get_bind()
    dialect_name = conn.dialect.name

    if dialect_name == "sqlite":
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")

    if dialect_name == "postgresql":
        _upgrade_postgresql(conn)
    else:
        _upgrade_sqlite(conn)

    if dialect_name == "sqlite":
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def _upgrade_sqlite(conn):
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
    # Indexes — ignore if exist
    for sql in [
        "CREATE INDEX IF NOT EXISTS ix_kg_nodes_rule_id ON kg_nodes (rule_id)",
        "CREATE INDEX IF NOT EXISTS ix_kg_nodes_type_status ON kg_nodes (node_type, audit_status)",
        "CREATE INDEX IF NOT EXISTS ix_kg_nodes_type_trust ON kg_nodes (node_type, trust_level)",
        "CREATE INDEX IF NOT EXISTS ix_kg_nodes_trust_level ON kg_nodes (trust_level)",
        "CREATE INDEX IF NOT EXISTS ix_kg_nodes_audit_status ON kg_nodes (audit_status)",
    ]:
        try:
            conn.exec_driver_sql(sql)
        except Exception:
            pass


def _upgrade_postgresql(conn):
    from sqlalchemy import MetaData, Table

    meta = MetaData()

    # Check if tables already exist
    existing = {row[1] for row in conn.execute(
        sa.text("SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema = 'public'")
    ).fetchall()}

    if "kg_nodes" not in existing:
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
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS ix_kg_nodes_rule_id ON kg_nodes (rule_id)",
            "CREATE INDEX IF NOT EXISTS ix_kg_nodes_type_status ON kg_nodes (node_type, audit_status)",
            "CREATE INDEX IF NOT EXISTS ix_kg_nodes_type_trust ON kg_nodes (node_type, trust_level)",
            "CREATE INDEX IF NOT EXISTS ix_kg_nodes_trust_level ON kg_nodes (trust_level)",
            "CREATE INDEX IF NOT EXISTS ix_kg_nodes_audit_status ON kg_nodes (audit_status)",
        ]:
            try:
                conn.execute(sa.text(idx_sql))
            except Exception:
                pass

    if "kg_edges" not in existing:
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
    """Drop kg_edges first (FK dependency), then kg_nodes."""
    conn = op.get_bind()
    dialect_name = conn.dialect.name

    if dialect_name == "sqlite":
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.exec_driver_sql("DROP TABLE IF EXISTS kg_edges")
        conn.exec_driver_sql("DROP TABLE IF EXISTS kg_nodes")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    else:
        op.drop_table("kg_edges")
        op.drop_table("kg_nodes")
