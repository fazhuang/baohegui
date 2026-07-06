"""dynamic_policy table for policy approval workflow

Create dynamic_policies table to persist policy records
with status state machine enforced by PolicyApprovalWorkflow.
"""

revision = "20260707_1000_dynamic_policies"
down_revision = "20260706_1000_feedback_isolation"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        "dynamic_policies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("policy_key", sa.String(128), unique=True, nullable=False),
        sa.Column("policy_type", sa.String(32), nullable=False, server_default="tenant"),
        sa.Column("policy_data", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft"),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("approval_note", sa.Text(), nullable=True),
        sa.Column("rejected_by", sa.Integer(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("applied_by", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("rolled_back_by", sa.Integer(), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(), nullable=True),
        sa.Column("rollback_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dynamic_policies_status", "dynamic_policies", ["status"])
    op.create_index("ix_dynamic_policies_type", "dynamic_policies", ["policy_type"])


def downgrade():
    op.drop_index("ix_dynamic_policies_type", table_name="dynamic_policies")
    op.drop_index("ix_dynamic_policies_status", table_name="dynamic_policies")
    op.drop_table("dynamic_policies")
