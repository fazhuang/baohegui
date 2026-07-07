"""Policy quarantine — permanent isolation of unverifiable historical records

For databases already stamped to 1200 or 1300, this migration:
- Adds is_quarantined / quarantined_at / quarantine_reason columns
- Backfills all records that were fixed by prior migrations (1200/1300)
  or that remain unverifiable by provenance
- Uses Python str.strip() for blank-detection (not SQL TRIM alone)
- Adds CHECK constraint: is_quarantined=true → status MUST be rolled_back

Key differentiation:
- Normal business rollback: is_quarantined=false, can revise → draft → re-approve
- Migration quarantine: is_quarantined=true, permanently blocked from execution
"""

revision = "20260707_1400_policy_quarantine"
down_revision = "20260707_1300_policy_scope_fix"
branch_labels = None
depends_on = None

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


# ── Sentinel scope_id values written by prior migrations ──
_MIGRATION_SCOPE_IDS = {
    "migration_fix_empty_scope",
    "migration_unscoped_global",
    "migration_fix_mismatch_type",
    "migration_fix_residual_mismatch",
}

# ── Migration fix reason prefixes ──
_MIGRATION_REASON_PREFIXES = (
    "migration_fix:",
    "migration_scope_",
    "migration_fix_",
)

# ── Python str.strip() blank check — matches Python semantics exactly ──
def _is_blank_scope(scope_id):
    """True if scope_id is None, not a string, or str.strip() is empty.
    Covers: "", "   ", "\\t", "\\n", "\\r", "\\v", "\\f", mixed, Unicode whitespace.
    """
    if scope_id is None:
        return True
    if not isinstance(scope_id, str):
        return True
    return scope_id.strip() == ""


# ── Identify quarantine-worthy records ──
def _should_quarantine(row):
    """Return (should_quarantine: bool, reason: str) for a row.

    A record must be quarantined if its provenance or integrity cannot be
    verified. This includes records:

    1. Fixed by prior migrations (1200 or 1300) — identified by:
       - rollback_reason starting with migration_fix: or migration_scope_
       - scope_id in the known migration sentinel set

    2. Still carrying illegal values:
       - Blank scope_id (Python str.strip() == "")
       - Illegal policy_type
       - Illegal scope_type
       - Illegal status
       - policy_type/scope_type mismatch

    3. scope_id='global' with scope_type != 'global' (provenance mismatch)
    """
    policy_type = row.get("policy_type")
    scope_type = row.get("scope_type")
    scope_id = row.get("scope_id")
    status = row.get("status")
    rollback_reason = row.get("rollback_reason") or ""

    # 1. Prior migration fix markers
    if rollback_reason.startswith(_MIGRATION_REASON_PREFIXES):
        return True, f"migration quarantine: prior fix detected — {rollback_reason[:120]}"

    if scope_id in _MIGRATION_SCOPE_IDS:
        return True, f"migration quarantine: sentinel scope_id={scope_id!r}"

    # 2. Blank scope_id (Python str.strip() semantics)
    if _is_blank_scope(scope_id):
        return True, "migration quarantine: blank scope_id"

    # 3. Illegal values
    if policy_type not in ("tenant", "platform"):
        return True, f"migration quarantine: illegal policy_type={policy_type!r}"

    if scope_type not in ("user", "platform", "global"):
        return True, f"migration quarantine: illegal scope_type={scope_type!r}"

    VALID_STATUSES = {"draft", "review", "approved", "rejected", "applied", "rolled_back"}
    if status not in VALID_STATUSES:
        return True, f"migration quarantine: illegal status={status!r}"

    # 4. Type/scope mismatch
    if policy_type == "tenant" and scope_type == "platform":
        return True, "migration quarantine: tenant policy with platform scope"
    if policy_type == "platform" and scope_type == "user":
        return True, "migration quarantine: platform policy with user scope"

    # 5. scope_id='global' with non-global scope_type
    if scope_id == "global" and scope_type != "global":
        return True, "migration quarantine: scope_id=global with non-global scope_type"

    return False, ""


def upgrade():
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    now_str = now.isoformat()

    # ── 1. Add quarantine columns ──
    # Use batch_alter_table for SQLite compatibility; works on PostgreSQL too.
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.add_column(
            sa.Column("is_quarantined", sa.Boolean(), nullable=False,
                      server_default=sa.text("false"),
                      comment="隔离标记：true=永久禁止状态转换和进入执行链"),
        )
        batch_op.add_column(
            sa.Column("quarantined_at", sa.DateTime(), nullable=True,
                      comment="隔离时间"),
        )
        batch_op.add_column(
            sa.Column("quarantine_reason", sa.Text(), nullable=True,
                      comment="隔离原因"),
        )

    # ── 2. Scan all rows with Python str.strip() semantics ──
    # Read all rows into Python for precise blank-detection and classification.
    rows = conn.execute(
        sa.text(
            "SELECT id, policy_key, policy_type, scope_type, scope_id, status, "
            "rollback_reason, rolled_back_at "
            "FROM dynamic_policies"
        )
    ).fetchall()

    # Convert to list of dicts
    all_rows = []
    for r in rows:
        all_rows.append({
            "id": r[0],
            "policy_key": r[1],
            "policy_type": r[2],
            "scope_type": r[3],
            "scope_id": r[4],
            "status": r[5],
            "rollback_reason": r[6],
            "rolled_back_at": r[7],
        })

    quarantine_ids = []
    for row in all_rows:
        should, reason = _should_quarantine(row)
        if should:
            quarantine_ids.append((row["id"], reason))

    # ── 3. Backfill quarantined records ──
    # For each quarantined record:
    #   is_quarantined = true
    #   quarantined_at = now
    #   quarantine_reason = reason
    #   status = 'rolled_back' (if not already)
    #   rolled_back_at = now (if NULL)
    #   rollback_reason preserved (set if NULL)
    #   updated_at = now
    for qid, reason in quarantine_ids:
        conn.execute(
            sa.text(
                "UPDATE dynamic_policies SET "
                "is_quarantined = true, "
                "quarantined_at = :now, "
                "quarantine_reason = :reason, "
                "status = 'rolled_back', "
                "rolled_back_at = COALESCE(rolled_back_at, :now), "
                "rollback_reason = COALESCE(rollback_reason, 'migration quarantine: unverifiable provenance'), "
                "updated_at = :now "
                "WHERE id = :id"
            ),
            {"now": now_str, "reason": reason, "id": qid},
        )

    # ── 4. Fix scope_id for blank records (Python strip semantics) ──
    # These records now have status=rolled_back, is_quarantined=true,
    # but their scope_id may still be blank — normalize to a sentinel.
    for row in all_rows:
        if _is_blank_scope(row["scope_id"]):
            conn.execute(
                sa.text(
                    "UPDATE dynamic_policies SET "
                    "scope_id = 'migration_fix_empty_scope', "
                    "updated_at = :now "
                    "WHERE id = :id"
                ),
                {"now": now_str, "id": row["id"]},
            )

    # ── 5. Add CHECK constraint: is_quarantined=true → status='rolled_back' ──
    # This prevents quarantined records from being set to draft/review/approved/applied
    # at the database level.
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.create_check_constraint(
            "ck_dynamic_policies_quarantine_status",
            "NOT (is_quarantined = true AND status <> 'rolled_back')",
        )


def downgrade():
    # ── Remove CHECK constraint ──
    with op.batch_alter_table("dynamic_policies") as batch_op:
        try:
            batch_op.drop_constraint("ck_dynamic_policies_quarantine_status")
        except Exception:
            pass

    # ── Drop quarantine columns ──
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.drop_column("quarantine_reason")
        batch_op.drop_column("quarantined_at")
        batch_op.drop_column("is_quarantined")
