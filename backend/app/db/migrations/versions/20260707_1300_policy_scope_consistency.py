"""Policy scope consistency — fix databases already stamped to old 1200

For databases that ran the SQLite-only 1200 migration with table-recreate:
- CHECK constraints were created inside the recreated table body (SQLite)
  but not via op.create_check_constraint — Alembic doesn't track them.
- This migration adds all constraints and indexes idempotently.
- For fresh PostgreSQL upgrades (1200 → 1300): all constraints already exist
  from new 1200; this migration detects and skips duplicates.

Safety: fixes illegal records before adding constraints.
"""

revision = "20260707_1300_policy_scope_fix"
down_revision = "20260707_1200_policy_constraints"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

# ── Inspector helpers ──


def _constraint_exists(conn, table_name: str, constraint_name: str) -> bool:
    """Check if a named constraint exists on the table (cross-dialect)."""
    inspector = sa_inspect(conn)
    check_constraints = inspector.get_check_constraints(table_name)
    for ck in check_constraints:
        if ck.get("name") == constraint_name:
            return True
    return False


def _index_exists(conn, table_name: str, index_name: str) -> bool:
    """Check if an index exists (cross-dialect)."""
    inspector = sa_inspect(conn)
    indexes = inspector.get_indexes(table_name)
    for idx in indexes:
        if idx.get("name") == index_name:
            return True
    return False


def _add_constraint_safe(conn, table_name: str, constraint_name: str,
                         condition: str) -> None:
    """Add a CHECK constraint only if it doesn't already exist."""
    if not _constraint_exists(conn, table_name, constraint_name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.create_check_constraint(constraint_name, condition)


def _add_index_safe(conn, table_name: str, index_name: str,
                    columns: list[str]) -> None:
    """Add an index only if it doesn't already exist."""
    if not _index_exists(conn, table_name, index_name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.create_index(index_name, columns)


def upgrade():
    conn = op.get_bind()

    # ── 1. Fix all illegal records BEFORE adding constraints ──
    # Strategy: every row that violates a future CHECK constraint gets
    # deterministically corrected. Applied rows → rolled_back (they were
    # executing with broken scope). Non-applied rows → repaired in place.

    # 1a. scope_type='global' but scope_id != 'global': fix scope_id
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("scope_id"), sa.column("scope_type"), sa.column("status"),
            sa.column("rollback_reason"), sa.column("rolled_back_at"), sa.column("updated_at"),
        ))
        .where(sa.column("scope_type") == "global")
        .where(sa.column("scope_id") != "global")
        .where(sa.column("status") == "applied")
        .values(
            status="rolled_back",
            rollback_reason="migration_fix: scope_type=global with scope_id!=global",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("scope_id"), sa.column("scope_type"),
        ))
        .where(sa.column("scope_type") == "global")
        .where(sa.column("scope_id") != "global")
        .where(sa.column("status") != "applied")
        .values(scope_id="global")
    )

    # 1b. Empty scope_ids — ALL rows rolled_back.  An empty scope_id
    # makes the policy's provenance unverifiable regardless of status.
    # Normalize scope_id to a placeholder so CHECK (TRIM(scope_id) <> '')
    # passes, but ROLL BACK every single row.
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("scope_id"), sa.column("status"),
            sa.column("rollback_reason"), sa.column("rolled_back_at"), sa.column("updated_at"),
        ))
        .where(sa.func.trim(sa.column("scope_id")) == "")
        .values(
            scope_id="migration_fix_empty_scope",
            status="rolled_back",
            rollback_reason="migration_fix: empty scope_id, cannot prove safe",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )

    # 1c. scope_type IN ('user','platform') with scope_id='global' — fix scope_id + roll back all
    # Must change scope_id, not just status — the CHECK constraint scans ALL rows.
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
            rollback_reason="migration_fix: non-global scope_type with scope_id=global",
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
            rollback_reason="migration_fix: non-global scope_type with scope_id=global",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )

    # 1d. policy_type/scope_type mismatch — fix scope_type AND roll back all
    # Changing only status is insufficient — the CHECK constraint scans ALL
    # rows including rolled_back. Must also correct the violating scope pair.
    for p_type, s_type, fix_scope, label in [
        ("tenant", "platform", "user", "tenant policy with platform scope"),
        ("platform", "user", "platform", "platform policy with user scope"),
    ]:
        op.execute(
            sa.update(sa.table(
                "dynamic_policies",
                sa.column("status"), sa.column("rollback_reason"),
                sa.column("rolled_back_at"), sa.column("updated_at"),
                sa.column("scope_type"), sa.column("scope_id"),
                sa.column("policy_type"),
            ))
            .where(sa.column("policy_type") == p_type)
            .where(sa.column("scope_type") == s_type)
            .where(sa.column("status") == "applied")
            .values(
                scope_type=fix_scope,
                scope_id="migration_fix_mismatch_type",
                status="rolled_back",
                rollback_reason=f"migration_fix: {label}",
                rolled_back_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
        )
        op.execute(
            sa.update(sa.table(
                "dynamic_policies",
                sa.column("status"), sa.column("rollback_reason"),
                sa.column("rolled_back_at"), sa.column("updated_at"),
                sa.column("scope_type"), sa.column("scope_id"),
                sa.column("policy_type"),
            ))
            .where(sa.column("policy_type") == p_type)
            .where(sa.column("scope_type") == s_type)
            .where(sa.column("status") != "applied")
            .values(
                scope_type=fix_scope,
                scope_id="migration_fix_mismatch_type",
                status="rolled_back",
                rollback_reason=f"migration_fix: {label}",
                rolled_back_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
        )

    # 1e. Illegal status values (including NULL) — rolled_back.
    # Cannot be repaired to draft because we cannot prove the record
    # was in a semantically valid state.
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("status"), sa.column("rollback_reason"),
            sa.column("rolled_back_at"), sa.column("updated_at"),
        ))
        .where(
            sa.or_(
                sa.column("status").is_(None),
                sa.column("status").notin_(
                    ["draft", "review", "approved", "rejected", "applied", "rolled_back"]
                ),
            )
        )
        .values(
            status="rolled_back",
            rollback_reason="migration_fix: illegal status value, cannot prove safe",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )

    # 1f. Illegal scope_type values — rolled_back for ALL rows, applied or not.
    # Normalize to 'global' to satisfy CHECK constraint, but ALWAYS roll back
    # because the original scope provenance is unverifiable.
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("scope_type"), sa.column("scope_id"),
            sa.column("status"), sa.column("rollback_reason"),
            sa.column("rolled_back_at"), sa.column("updated_at"),
        ))
        .where(
            sa.or_(
                sa.column("scope_type").is_(None),
                sa.column("scope_type").notin_(["user", "platform", "global"]),
            )
        )
        .values(
            scope_type="global", scope_id="global",
            status="rolled_back",
            rollback_reason="migration_fix: illegal scope_type, cannot prove safe",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )

    # 1g. Illegal policy_type values (including NULL) — rolled_back for ALL rows.
    # Normalize to a CHECK-safe type keyed on scope, but ALWAYS roll back.
    # Scope that is itself illegal was already normalized to 'global' by 1f,
    # so the else-branch handles those.
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("policy_type"), sa.column("status"),
            sa.column("rollback_reason"), sa.column("rolled_back_at"), sa.column("updated_at"),
            sa.column("scope_type"),
        ))
        .where(
            sa.or_(
                sa.column("policy_type").is_(None),
                sa.column("policy_type").notin_(["tenant", "platform"]),
            )
        )
        .where(sa.column("scope_type") == "platform")
        .values(
            policy_type="platform",
            status="rolled_back",
            rollback_reason="migration_fix: illegal policy_type, cannot prove safe (→platform from scope)",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )
    op.execute(
        sa.update(sa.table(
            "dynamic_policies",
            sa.column("policy_type"), sa.column("status"),
            sa.column("rollback_reason"), sa.column("rolled_back_at"), sa.column("updated_at"),
        ))
        .where(
            sa.or_(
                sa.column("policy_type").is_(None),
                sa.column("policy_type").notin_(["tenant", "platform"]),
            )
        )
        .where(sa.column("scope_type") != "platform")
        .values(
            policy_type="tenant",
            status="rolled_back",
            rollback_reason="migration_fix: illegal policy_type, cannot prove safe (→tenant)",
            rolled_back_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )

    # 1h. Final safety scan: after all fixes, verify no type/scope mismatch remains.
    # Any surviving mismatch is rolled back with scope corrected.
    for p_type, s_type, fix_scope, label in [
        ("tenant", "platform", "user", "residual tenant+platform after fix pass"),
        ("platform", "user", "platform", "residual platform+user after fix pass"),
    ]:
        op.execute(
            sa.update(sa.table(
                "dynamic_policies",
                sa.column("status"), sa.column("rollback_reason"),
                sa.column("rolled_back_at"), sa.column("updated_at"),
                sa.column("scope_type"), sa.column("scope_id"),
                sa.column("policy_type"),
            ))
            .where(sa.column("policy_type") == p_type)
            .where(sa.column("scope_type") == s_type)
            .values(
                scope_type=fix_scope,
                scope_id="migration_fix_residual_mismatch",
                status="rolled_back",
                rollback_reason=f"migration_fix: {label}",
                rolled_back_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
        )

    # ── 2. Add all CHECK constraints idempotently ──
    _add_constraint_safe(
        conn, "dynamic_policies",
        "ck_dynamic_policies_scope_type",
        "scope_type IN ('user','platform','global')",
    )
    _add_constraint_safe(
        conn, "dynamic_policies",
        "ck_dynamic_policies_status",
        "status IN ('draft','review','approved','rejected','applied','rolled_back')",
    )
    _add_constraint_safe(
        conn, "dynamic_policies",
        "ck_dynamic_policies_policy_type",
        "policy_type IN ('tenant','platform')",
    )
    _add_constraint_safe(
        conn, "dynamic_policies",
        "ck_dynamic_policies_scope_id_not_empty",
        "TRIM(scope_id) <> ''",
    )
    _add_constraint_safe(
        conn, "dynamic_policies",
        "ck_dynamic_policies_global_scope_id",
        "NOT (scope_type = 'global' AND scope_id <> 'global')",
    )
    _add_constraint_safe(
        conn, "dynamic_policies",
        "ck_dynamic_policies_non_global_scope_id",
        "NOT (scope_type IN ('user','platform') AND scope_id = 'global')",
    )
    _add_constraint_safe(
        conn, "dynamic_policies",
        "ck_dynamic_policies_type_scope_pair",
        "NOT (policy_type = 'tenant' AND scope_type = 'platform')",
    )
    _add_constraint_safe(
        conn, "dynamic_policies",
        "ck_dynamic_policies_type_scope_pair2",
        "NOT (policy_type = 'platform' AND scope_type = 'user')",
    )

    # ── 3. Ensure indexes exist ──
    _add_index_safe(
        conn, "dynamic_policies",
        "ix_dynamic_policies_scope",
        ["status", "policy_type", "scope_type", "scope_id"],
    )
    _add_index_safe(
        conn, "dynamic_policies",
        "ix_dynamic_policies_status",
        ["status"],
    )
    _add_index_safe(
        conn, "dynamic_policies",
        "ix_dynamic_policies_type",
        ["policy_type"],
    )

    # ── 4. Drop server_default if still present (legacy 1100 upgrade path) ──
    inspector = sa_inspect(conn)
    columns_info = {c["name"]: c for c in inspector.get_columns("dynamic_policies")}
    for col_name in ("scope_type", "scope_id"):
        col = columns_info.get(col_name)
        if col and col.get("default") is not None:
            with op.batch_alter_table("dynamic_policies") as batch_op:
                batch_op.alter_column(col_name, server_default=None)


def downgrade():
    # Cannot reverse a fix pass — skip
    pass
