"""dynamic_policy DB constraints — CHECK + NOT NULL + scope hardening

Add CHECK constraints for scope_type, status, policy_type.
Remove scope server_defaults (explicit scope required for new records).
Handle historical applied global policies: rollback with migration reason.

Cross-dialect: uses SQLAlchemy operations with batch_alter_table for SQLite,
native ALTER TABLE for PostgreSQL. Same business semantics on both.
"""

revision = "20260707_1200_policy_constraints"
down_revision = "20260707_1100_policy_scope"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _add_check_constraints():
    """Add CHECK constraints. Uses batch_alter_table for SQLite compatibility.

    PostgreSQL handles CHECK directly via op.create_check_constraint.
    SQLite batch_alter_table supports named check constraints.
    """
    # scope_type IN ('user','platform','global')
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.create_check_constraint(
            "ck_dynamic_policies_scope_type",
            "scope_type IN ('user','platform','global')",
        )
    # status IN ('draft','review','approved','rejected','applied','rolled_back')
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.create_check_constraint(
            "ck_dynamic_policies_status",
            "status IN ('draft','review','approved','rejected','applied','rolled_back')",
        )
    # policy_type IN ('tenant','platform')
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.create_check_constraint(
            "ck_dynamic_policies_policy_type",
            "policy_type IN ('tenant','platform')",
        )
    # scope_id not empty
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.create_check_constraint(
            "ck_dynamic_policies_scope_id_not_empty",
            "TRIM(scope_id) <> ''",
        )
    # scope_type='global' => scope_id='global'
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.create_check_constraint(
            "ck_dynamic_policies_global_scope_id",
            "NOT (scope_type = 'global' AND scope_id <> 'global')",
        )
    # scope_type IN ('user','platform') => scope_id <> 'global'
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.create_check_constraint(
            "ck_dynamic_policies_non_global_scope_id",
            "NOT (scope_type IN ('user','platform') AND scope_id = 'global')",
        )
    # policy_type/scope_type pairing:
    # tenant → user or global; platform → platform or global
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.create_check_constraint(
            "ck_dynamic_policies_type_scope_pair",
            "NOT (policy_type = 'tenant' AND scope_type = 'platform')",
        )
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.create_check_constraint(
            "ck_dynamic_policies_type_scope_pair2",
            "NOT (policy_type = 'platform' AND scope_type = 'user')",
        )


def _rebuild_composite_index():
    """Ensure composite loader index exists (idempotent)."""
    # Use raw SQL via execute — both dialects support CREATE INDEX IF NOT EXISTS
    # (SQLite 3.25+, PostgreSQL 9.5+)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dynamic_policies_scope "
        "ON dynamic_policies (status, policy_type, scope_type, scope_id)"
    )


def upgrade():
    # ── 0. Fix all illegal rows BEFORE adding CHECK constraints ──
    # Each future constraint must pass for every existing row.
    # Strategy: applied → rolled_back, non-applied → repaired in place.

    # 0a. Illegal scope_type → reset to safe default
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("scope_type"), sa.column("scope_id"),
            sa.column("status"), sa.column("rollback_reason"),
            sa.column("rolled_back_at"), sa.column("updated_at"),
        ))
        .where(sa.column("scope_type").notin_(["user", "platform", "global"]))
        .where(sa.column("status") == "applied")
        .values(
            scope_type="global", scope_id="global",
            status="rolled_back",
            rollback_reason="migration_scope_repair: illegal scope_type, rolled back",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )
    op.execute(
        sa.update(sa.table(
            "dynamic_policies", sa.column("scope_type"), sa.column("scope_id"),
        ))
        .where(sa.column("scope_type").notin_(["user", "platform", "global"]))
        .where(sa.column("status") != "applied")
        .values(scope_type="global", scope_id="global")
    )

    # 0b. Illegal policy_type → reset
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("policy_type"), sa.column("status"),
            sa.column("rollback_reason"), sa.column("rolled_back_at"),
            sa.column("updated_at"),
        ))
        .where(sa.column("policy_type").notin_(["tenant", "platform"]))
        .where(sa.column("status") == "applied")
        .values(
            policy_type="tenant",
            status="rolled_back",
            rollback_reason="migration_scope_repair: illegal policy_type, rolled back",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )
    op.execute(
        sa.update(sa.table("dynamic_policies", sa.column("policy_type")))
        .where(sa.column("policy_type").notin_(["tenant", "platform"]))
        .where(sa.column("status") != "applied")
        .values(policy_type="tenant")
    )

    # 0c. Illegal status values → draft
    op.execute(
        sa.update(sa.table("dynamic_policies", sa.column("status")))
        .where(sa.column("status").notin_(
            ["draft", "review", "approved", "rejected", "applied", "rolled_back"]
        ))
        .values(status="draft")
    )

    # 0d. scope_type='global' but scope_id != 'global'
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("status"), sa.column("rollback_reason"),
            sa.column("rolled_back_at"), sa.column("updated_at"),
            sa.column("scope_id"), sa.column("scope_type"),
        ))
        .where(sa.column("scope_type") == "global")
        .where(sa.column("scope_id") != "global")
        .where(sa.column("status") == "applied")
        .values(
            status="rolled_back",
            rollback_reason="migration_scope_repair: scope_type=global with scope_id!=global",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )
    op.execute(
        sa.update(sa.table("dynamic_policies", sa.column("scope_id")))
        .where(sa.column("scope_type") == "global")
        .where(sa.column("scope_id") != "global")
        .where(sa.column("status") != "applied")
        .values(scope_id="global")
    )

    # 0e. Empty scope_id
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("status"), sa.column("rollback_reason"),
            sa.column("rolled_back_at"), sa.column("updated_at"),
            sa.column("scope_id"),
        ))
        .where(sa.func.trim(sa.column("scope_id")) == "")
        .where(sa.column("status") == "applied")
        .values(
            status="rolled_back",
            rollback_reason="migration_scope_repair: empty scope_id",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )
    op.execute(
        sa.update(sa.table("dynamic_policies", sa.column("scope_id")))
        .where(sa.func.trim(sa.column("scope_id")) == "")
        .where(sa.column("status") != "applied")
        .values(scope_id="migration_fix_empty_scope")
    )

    # 0f. scope_type IN ('user','platform') with scope_id='global'
    # Must change scope_id too, NOT just rollback — the CHECK constraint
    # scans ALL rows including rolled_back ones.
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("status"), sa.column("rollback_reason"),
            sa.column("rolled_back_at"), sa.column("updated_at"),
            sa.column("scope_id"), sa.column("scope_type"),
        ))
        .where(sa.column("scope_type").in_(["user", "platform"]))
        .where(sa.column("scope_id") == "global")
        .where(sa.column("status") == "applied")
        .values(
            scope_id="migration_unscoped_global",
            status="rolled_back",
            rollback_reason="migration_scope_repair: non-global scope_type with scope_id=global",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("scope_id"), sa.column("status"), sa.column("rollback_reason"),
            sa.column("rolled_back_at"), sa.column("updated_at"),

        ))
        .where(sa.column("scope_type").in_(["user", "platform"]))
        .where(sa.column("scope_id") == "global")
        .where(sa.column("status") != "applied")
        .values(
            scope_id="migration_unscoped_global",
            status="rolled_back",
            rollback_reason="migration_scope_repair: non-global scope_type with scope_id=global",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )

    # 0g. policy_type/scope_type mismatch
    # Must change scope_type too, not just rollback — CHECK scans all rows.
    for p_type_str, s_type_str, fix_scope, label in [
        ("tenant", "platform", "user", "tenant with platform scope"),
        ("platform", "user", "platform", "platform with user scope"),
    ]:
        op.execute(
            sa.update(sa.table(
                "dynamic_policies",
                sa.column("status"), sa.column("rollback_reason"),
                sa.column("rolled_back_at"), sa.column("updated_at"),
                sa.column("scope_id"), sa.column("scope_type"), sa.column("policy_type"),
            ))
            .where(sa.column("policy_type") == p_type_str)
            .where(sa.column("scope_type") == s_type_str)
            .where(sa.column("status") == "applied")
            .values(
                scope_type=fix_scope,
                scope_id="migration_fix_mismatch_type",
                status="rolled_back",
                rollback_reason=f"migration_scope_repair: {label}",
                rolled_back_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
        )
        op.execute(
            sa.update(sa.table(
                "dynamic_policies",
                sa.column("status"), sa.column("rollback_reason"),
                sa.column("rolled_back_at"), sa.column("updated_at"),
                sa.column("scope_id"), sa.column("scope_type"), sa.column("policy_type"),
            ))
            .where(sa.column("policy_type") == p_type_str)
            .where(sa.column("scope_type") == s_type_str)
            .where(sa.column("status") != "applied")
            .values(
                scope_type=fix_scope,
                scope_id="migration_fix_mismatch_type",
                status="rolled_back",
                rollback_reason=f"migration_scope_repair: {label}",
                rolled_back_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
        )

    # ── 1. Historical applied global policies (explicit rollback) ──
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("status"), sa.column("rollback_reason"),
            sa.column("rolled_back_at"), sa.column("updated_at"),
            sa.column("scope_type"), sa.column("scope_id"),
        ))
        .where(sa.column("status") == "applied")
        .where(sa.column("scope_type") == "global")
        .where(sa.column("scope_id") == "global")
        .values(
            status="rolled_back",
            rollback_reason="migration_scope_unverifiable: scope=global/global cannot be proved user-scoped",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )

    # ── 2. Drop server_default on scope columns ──
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.alter_column("scope_type", server_default=None, existing_nullable=False)
        batch_op.alter_column("scope_id", server_default=None, existing_nullable=False)

    # ── 3. Recreate composite loader index ──
    _rebuild_composite_index()

    # ── 4. Add CHECK constraints ──
    _add_check_constraints()

    # ── 5. Ensure status/policy_type indexes exist ──
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dynamic_policies_status "
        "ON dynamic_policies (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dynamic_policies_type "
        "ON dynamic_policies (policy_type)"
    )


def downgrade():
    # ── Remove CHECK constraints ──
    constraint_names = [
        "ck_dynamic_policies_scope_type",
        "ck_dynamic_policies_status",
        "ck_dynamic_policies_policy_type",
        "ck_dynamic_policies_scope_id_not_empty",
        "ck_dynamic_policies_global_scope_id",
        "ck_dynamic_policies_non_global_scope_id",
        "ck_dynamic_policies_type_scope_pair",
        "ck_dynamic_policies_type_scope_pair2",
    ]
    with op.batch_alter_table("dynamic_policies") as batch_op:
        for ck_name in constraint_names:
            try:
                batch_op.drop_constraint(ck_name)
            except Exception:
                pass  # Constraint may not exist if upgrade was partial

    # ── Restore server_default on scope columns ──
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.alter_column("scope_type", server_default="global", existing_nullable=False)
        batch_op.alter_column("scope_id", server_default="global", existing_nullable=False)
