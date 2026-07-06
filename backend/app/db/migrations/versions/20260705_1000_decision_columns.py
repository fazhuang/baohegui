"""add decision columns with constraints to compliance_reports

Revision ID: 20260705_1000_decision_columns
Revises: 20260705_1600_bridge_core_reports
Create Date: 2026-07-05 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = '20260705_1000_decision_columns'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CHECK_DEFS = [
    ("ck_decision_action",
     "decision_action IN ('pass', 'warn', 'require_review', 'block') OR decision_action IS NULL"),
    ("ck_decision_risk_level",
     "decision_risk_level IN ('low', 'medium', 'high', 'critical') OR decision_risk_level IS NULL"),
    ("ck_decision_integrity_status",
     "decision_integrity_status IN ('verified', 'legacy_unverifiable', 'integrity_failed') OR decision_integrity_status IS NULL"),
    ("ck_decision_requires_human_review",
     "decision_requires_human_review IN (0, 1) OR decision_requires_human_review IS NULL"),
]

# Columns this migration may add to an existing table. We list them so the
# SQLite rebuild knows what extra columns to include. Each is
# (name, sql_type, col_obj) — col_obj for SA-level introspection.
_DECISION_COLUMNS = [
    ("decision_action", "VARCHAR(32)", sa.Column("decision_action", sa.String(32), nullable=True)),
    ("decision_risk_level", "VARCHAR(16)", sa.Column("decision_risk_level", sa.String(16), nullable=True)),
    ("decision_requires_human_review", "BOOLEAN", sa.Column("decision_requires_human_review", sa.Boolean(), nullable=True)),
    ("decision_hash", "VARCHAR(64)", sa.Column("decision_hash", sa.String(64), nullable=True)),
    ("policy_schema_version", "VARCHAR(16)", sa.Column("policy_schema_version", sa.String(16), nullable=True)),
    ("decision_integrity_status", "VARCHAR(32)", sa.Column("decision_integrity_status", sa.String(32), nullable=True)),
]


def _column_exists(conn, table: str, column: str) -> bool:
    insp = Inspector.from_engine(conn)
    cols = [c["name"] for c in insp.get_columns(table)]
    return column in cols


def _constraint_exists(conn, table: str, ck_name: str) -> bool:
    """Check if a named CHECK constraint already exists on the table."""
    insp = Inspector.from_engine(conn)
    for c in insp.get_check_constraints(table):
        if c.get("name") == ck_name:
            return True
    return False


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    # ── 添加决策列（幂等） ──
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

    # ── 数据库约束 ──
    if dialect == "sqlite":
        _ensure_constraints_sqlite(conn)
    else:
        _ensure_constraints_postgresql(conn)

    # ── 历史记录标记 legacy_unverifiable ──
    conn.execute(
        sa.text("UPDATE compliance_reports SET decision_integrity_status = 'legacy_unverifiable' "
                "WHERE decision_integrity_status IS NULL AND decision_action IS NULL")
    )


def _ensure_constraints_sqlite(conn):
    """SQLite: rebuild the table via raw DDL to include CHECK constraints.

    SQLite only supports CHECK constraints inline in CREATE TABLE.
    Alembic's batch_alter_table + create_check_constraint does not
    emit them into the DDL. We introspect the current schema, build
    a new CREATE TABLE with the CHECKs included, copy all data, and
    swap tables.
    """
    # Build CHECK predicates as inline SQL (unnamed — SQLite doesn't
    # support named CHECK constraints; the Inspector may report names
    # but they aren't part of the DDL).
    check_sql = ",\n    ".join(f"CHECK({cond})" for _, cond in _CHECK_DEFS)

    # Introspect current columns and their types from the live table.
    insp = Inspector.from_engine(conn)
    existing_cols = insp.get_columns("compliance_reports")
    existing_col_names = {c["name"] for c in existing_cols}

    # Ensure all decision columns exist before rebuild.
    for col_name, _, _ in _DECISION_COLUMNS:
        if col_name not in existing_col_names:
            raise RuntimeError(
                f"Column {col_name} is missing before SQLite constraint rebuild. "
                f"This migration requires all decision columns to be added first."
            )

    # Refresh introspection after column additions.
    # alembic add_column creates actual columns; we just introspected above.
    # Build column DDL from the live table.
    col_defs = []
    pk_cols = []
    fk_defs = []
    all_col_names = []

    for c in insp.get_columns("compliance_reports"):
        cname = c["name"]
        all_col_names.append(cname)
        ctype = c["type"]
        nullable = c.get("nullable", True)
        default = c.get("default")

        # Determine SQL type string
        type_str = _sqlite_type_str(ctype)

        col_parts = [cname, type_str]

        # Primary key
        if c.get("primary_key"):
            if isinstance(ctype, sa.Integer):
                col_parts.append("PRIMARY KEY AUTOINCREMENT")
            else:
                col_parts.append("PRIMARY KEY")
            pk_cols.append(cname)
            nullable = False  # PK is never null

        # Nullable
        if not nullable:
            col_parts.append("NOT NULL")

        # Default
        if default is not None:
            default_val = _format_sqlite_default(default)
            if default_val is not None:
                col_parts.append(f"DEFAULT {default_val}")

        col_defs.append(" ".join(col_parts))

    # Foreign keys via PRAGMA
    for fk_row in conn.execute(sa.text("PRAGMA foreign_key_list(compliance_reports)")).fetchall():
        # PRAGMA foreign_key_list columns: id, seq, table, from, to, on_update, on_delete, match
        fk_from = fk_row[3]
        fk_ref_table = fk_row[2]
        fk_ref_col = fk_row[4]
        fk_defs.append(f"FOREIGN KEY({fk_from}) REFERENCES {fk_ref_table}({fk_ref_col})")

    # Assemble CREATE TABLE
    all_defs = col_defs + fk_defs + [check_sql]
    create_sql = f"CREATE TABLE _compliance_reports_new (\n    {',\n    '.join(all_defs)}\n)"
    all_col_names_str = ", ".join(all_col_names)

    # Rebuild: create new table, copy data, drop old, rename
    conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    try:
        conn.execute(sa.text(create_sql))
        conn.execute(sa.text(
            f"INSERT INTO _compliance_reports_new ({all_col_names_str}) "
            f"SELECT {all_col_names_str} FROM compliance_reports"
        ))
        conn.execute(sa.text("DROP TABLE compliance_reports"))
        conn.execute(sa.text("ALTER TABLE _compliance_reports_new RENAME TO compliance_reports"))
    finally:
        conn.execute(sa.text("PRAGMA foreign_keys=ON"))

    # Recreate indexes
    for idx in insp.get_indexes("compliance_reports"):
        # After rename, indexes should be rechecked; new table has no indexes
        # But since we dropped the old table, its indexes are gone — Alembic
        # handles this for batch_alter_table. For raw rebuild we need to
        # manually recreate. However, our compliance_reports table has never
        # had custom indexes in migrations — so this is a noop for now.
        pass


def _sqlite_type_str(sa_type) -> str:
    """Map SQLAlchemy type to a SQLite type string suitable for DDL."""
    import sqlalchemy as sa
    if isinstance(sa_type, sa.Integer):
        return "INTEGER"
    if isinstance(sa_type, sa.BigInteger):
        return "INTEGER"
    if isinstance(sa_type, sa.Float):
        return "FLOAT"
    if isinstance(sa_type, sa.Boolean):
        return "BOOLEAN"
    if isinstance(sa_type, sa.DateTime):
        return "DATETIME"
    if isinstance(sa_type, sa.Date):
        return "DATE"
    if isinstance(sa_type, sa.Text):
        return "TEXT"
    # String/VARCHAR variants
    if isinstance(sa_type, (sa.String, sa.VARCHAR)):
        if sa_type.length:
            return f"VARCHAR({sa_type.length})"
        return "TEXT"
    return "TEXT"


def _format_sqlite_default(default: str) -> str | None:
    """Format a column default value for SQLite DDL.

    Returns a string like '0', 'CURRENT_TIMESTAMP', or "'legacy_unverifiable'".
    Returns None if the default should be dropped (server-side functions we
    can't reproduce).

    The SQLAlchemy Inspector returns string defaults already quoted as SQL
    literals (e.g. "'legacy_unverifiable'").  We must normalize these so we
    don't produce triple-quoted garbage like '''legacy_unverifiable'''.
    """
    default = str(default).strip()
    if not default:
        return None

    # Strip outer parentheses — some SQLite versions wrap defaults.
    if default.startswith("(") and default.endswith(")"):
        default = default[1:-1].strip()

    # ── Already a SQL string literal (single-quoted) → normalize ──
    if len(default) >= 2 and default[0] == "'" and default[-1] == "'":
        inner = default[1:-1].replace("''", "'")  # SQL unescape
        # Numeric literal disguised as string?
        try:
            float(inner)
            return inner
        except ValueError:
            pass
        # SQL keyword?
        if inner.upper() in ("CURRENT_TIMESTAMP", "CURRENT_DATE", "CURRENT_TIME", "NULL"):
            return inner.upper()
        # String literal — re-quote with proper escaping
        escaped = inner.replace("'", "''")
        return f"'{escaped}'"

    # ── Unquoted values ──
    if default.upper() in ("CURRENT_TIMESTAMP", "CURRENT_DATE", "CURRENT_TIME"):
        return default
    if default.upper() in ("NULL",):
        return "NULL"
    if default in ("0", "1", "0.0", "1.0"):
        return default
    # Try numeric
    try:
        float(default)
        return default
    except ValueError:
        pass
    # Bare string — quote it
    escaped = default.replace("'", "''")
    return f"'{escaped}'"


def _ensure_constraints_postgresql(conn):
    """PostgreSQL: add named CHECK constraints only if missing. Fail on error."""
    for ck_name, condition in _CHECK_DEFS:
        if _constraint_exists(conn, "compliance_reports", ck_name):
            continue
        op.create_check_constraint(ck_name, "compliance_reports", condition)


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        _downgrade_sqlite(conn)
    else:
        for ck_name, _ in _CHECK_DEFS:
            if _constraint_exists(conn, "compliance_reports", ck_name):
                op.drop_constraint(ck_name, "compliance_reports", type_="check")
        for col_name, _, _ in _DECISION_COLUMNS:
            if _column_exists(conn, "compliance_reports", col_name):
                op.drop_column("compliance_reports", col_name)


def _downgrade_sqlite(conn):
    """SQLite: rebuild the table without decision columns and CHECK constraints.

    Since SQLite cannot drop columns directly, we rebuild the table copying
    only non-decision columns.
    """
    insp = Inspector.from_engine(conn)
    existing_cols = insp.get_columns("compliance_reports")
    decision_col_names = {dc[0] for dc in _DECISION_COLUMNS}

    keep_cols = [c for c in existing_cols if c["name"] not in decision_col_names]
    keep_names = [c["name"] for c in keep_cols]

    col_defs = []
    for c in keep_cols:
        cname = c["name"]
        ctype = c["type"]
        nullable = c.get("nullable", True)
        default = c.get("default")

        type_str = _sqlite_type_str(ctype)
        col_parts = [cname, type_str]

        if c.get("primary_key"):
            if isinstance(ctype, sa.Integer):
                col_parts.append("PRIMARY KEY AUTOINCREMENT")
            else:
                col_parts.append("PRIMARY KEY")

        if not nullable:
            col_parts.append("NOT NULL")

        if default is not None:
            default_val = _format_sqlite_default(default)
            if default_val is not None:
                col_parts.append(f"DEFAULT {default_val}")

        col_defs.append(" ".join(col_parts))

    # Foreign keys
    fk_defs = []
    for fk_row in conn.execute(sa.text("PRAGMA foreign_key_list(compliance_reports)")).fetchall():
        fk_from = fk_row[3]
        if fk_from in decision_col_names:
            continue
        fk_ref_table = fk_row[2]
        fk_ref_col = fk_row[4]
        fk_defs.append(f"FOREIGN KEY({fk_from}) REFERENCES {fk_ref_table}({fk_ref_col})")

    all_defs = col_defs + fk_defs
    create_sql = f"CREATE TABLE _compliance_reports_downgrade (\n    {',\n    '.join(all_defs)}\n)"
    keep_names_str = ", ".join(keep_names)

    conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    try:
        conn.execute(sa.text(create_sql))
        conn.execute(sa.text(
            f"INSERT INTO _compliance_reports_downgrade ({keep_names_str}) "
            f"SELECT {keep_names_str} FROM compliance_reports"
        ))
        conn.execute(sa.text("DROP TABLE compliance_reports"))
        conn.execute(sa.text("ALTER TABLE _compliance_reports_downgrade RENAME TO compliance_reports"))
    finally:
        conn.execute(sa.text("PRAGMA foreign_keys=ON"))
