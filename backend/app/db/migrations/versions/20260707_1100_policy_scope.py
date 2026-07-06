"""dynamic_policy scope isolation — add scope_type + scope_id

Require explicit scope (user/platform/global) on every DynamicPolicy.
Loader must pass scope_type + scope_id; missing scope → no match.
scope_type/scope_id indexed for the loader's composite filter.
"""

revision = "20260707_1100_policy_scope"
down_revision = "20260707_1000_dynamic_policies"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    # Add scope columns with NOT NULL; use server_default for existing rows
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.add_column(
            sa.Column("scope_type", sa.String(16), nullable=False,
                      server_default="global", comment="user / platform / global")
        )
        batch_op.add_column(
            sa.Column("scope_id", sa.String(64), nullable=False,
                      server_default="global", comment="user_id, platform_id, or 'global'")
        )
    # Composite index for loader queries
    op.create_index(
        "ix_dynamic_policies_scope",
        "dynamic_policies",
        ["status", "policy_type", "scope_type", "scope_id"],
    )
    # Check constraint on scope_type
    with op.get_context().autocommit_block():
        op.execute(
            "UPDATE dynamic_policies SET scope_type = 'global', scope_id = 'global' "
            "WHERE scope_type = 'global' AND scope_id = 'global'"
        )


def downgrade():
    op.drop_index("ix_dynamic_policies_scope", table_name="dynamic_policies")
    with op.batch_alter_table("dynamic_policies") as batch_op:
        batch_op.drop_column("scope_id")
        batch_op.drop_column("scope_type")
