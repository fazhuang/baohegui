"""dynamic_policy DB constraints — CHECK + NOT NULL + scope hardening

Add CHECK constraints for scope_type, status, policy_type.
Remove scope server_defaults (explicit scope required for new records).
Handle historical applied global policies: rollback with migration reason.
"""

revision = "20260707_1200_policy_constraints"
down_revision = "20260707_1100_policy_scope"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    # ── 1. Handle historical applied global policies ──
    # Any applied policy with scope='global' whose original scope is unverifiable
    # must be rolled back. We can only trust records created after this migration.
    # We mark these with a distinct rollback_reason and status='rolled_back'.
    op.execute(
        "UPDATE dynamic_policies "
        "SET status = 'rolled_back', "
        "    rollback_reason = 'migration_scope_unverifiable: scope=global/global cannot be proved user-scoped', "
        "    rolled_back_at = datetime('now'), "
        "    updated_at = datetime('now') "
        "WHERE status = 'applied' "
        "  AND scope_type = 'global' "
        "  AND scope_id = 'global'"
    )

    # ── 2. Drop server_default on scope columns (explicit scope required going forward) ──
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.alter_column("scope_type", server_default=None, existing_nullable=False)
        batch_op.alter_column("scope_id", server_default=None, existing_nullable=False)

    # ── 3. Recreate the composite loader index (idempotent) ──
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dynamic_policies_scope "
        "ON dynamic_policies (status, policy_type, scope_type, scope_id)"
    )

    # ── 4. CHECK constraints ──
    # SQLite requires recreating the table to add CHECK constraints.
    # We create a new table with constraints, copy data, drop old, rename.
    op.execute("""
        CREATE TABLE dynamic_policies_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_key VARCHAR(128) NOT NULL UNIQUE,
            policy_type VARCHAR(32) NOT NULL DEFAULT 'tenant'
                CHECK (policy_type IN ('tenant', 'platform')),
            scope_type VARCHAR(16) NOT NULL
                CHECK (scope_type IN ('user', 'platform', 'global')),
            scope_id VARCHAR(64) NOT NULL,
            policy_data TEXT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'review', 'approved', 'rejected', 'applied', 'rolled_back')),
            submitted_at DATETIME,
            approved_by INTEGER,
            approved_at DATETIME,
            approval_note TEXT,
            rejected_by INTEGER,
            rejected_at DATETIME,
            rejection_reason TEXT,
            applied_by INTEGER,
            applied_at DATETIME,
            rolled_back_by INTEGER,
            rolled_back_at DATETIME,
            rollback_reason TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER,
            description TEXT
        )
    """)

    # Copy all data with explicit column list (safe against column count mismatches)
    op.execute("""
        INSERT INTO dynamic_policies_new (
            id, policy_key, policy_type, scope_type, scope_id, policy_data, status,
            submitted_at, approved_by, approved_at, approval_note,
            rejected_by, rejected_at, rejection_reason,
            applied_by, applied_at,
            rolled_back_by, rolled_back_at, rollback_reason,
            created_at, updated_at, created_by, description
        )
        SELECT
            id, policy_key, policy_type, scope_type, scope_id, policy_data, status,
            submitted_at, approved_by, approved_at, approval_note,
            rejected_by, rejected_at, rejection_reason,
            applied_by, applied_at,
            rolled_back_by, rolled_back_at, rollback_reason,
            created_at, updated_at, created_by, description
        FROM dynamic_policies
    """)

    # Drop old table
    op.execute("DROP TABLE dynamic_policies")

    # Rename new table
    op.execute("ALTER TABLE dynamic_policies_new RENAME TO dynamic_policies")

    # Rebuild indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dynamic_policies_status "
        "ON dynamic_policies (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dynamic_policies_type "
        "ON dynamic_policies (policy_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dynamic_policies_scope "
        "ON dynamic_policies (status, policy_type, scope_type, scope_id)"
    )


def downgrade():
    # Rebuild without CHECK constraints
    op.execute("""
        CREATE TABLE dynamic_policies_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_key VARCHAR(128) NOT NULL UNIQUE,
            policy_type VARCHAR(32) NOT NULL DEFAULT 'tenant',
            scope_type VARCHAR(16) NOT NULL DEFAULT 'global',
            scope_id VARCHAR(64) NOT NULL DEFAULT 'global',
            policy_data TEXT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'draft',
            submitted_at DATETIME,
            approved_by INTEGER,
            approved_at DATETIME,
            approval_note TEXT,
            rejected_by INTEGER,
            rejected_at DATETIME,
            rejection_reason TEXT,
            applied_by INTEGER,
            applied_at DATETIME,
            rolled_back_by INTEGER,
            rolled_back_at DATETIME,
            rollback_reason TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER,
            description TEXT
        )
    """)

    op.execute("INSERT INTO dynamic_policies_old SELECT * FROM dynamic_policies")
    op.execute("DROP TABLE dynamic_policies")
    op.execute("ALTER TABLE dynamic_policies_old RENAME TO dynamic_policies")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dynamic_policies_status "
        "ON dynamic_policies (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dynamic_policies_type "
        "ON dynamic_policies (policy_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dynamic_policies_scope "
        "ON dynamic_policies (status, policy_type, scope_type, scope_id)"
    )
