"""feedback_execution_isolation — 幂等约束 + 反馈事件表重命名

变更:
- 新建 feedback_events 表（含 uq_feedback_user_report_rule 唯一约束）
- 添加 status + 管理员审计列
- 保留 feedback_records 和 rule_confidences 作为遗留表（不删除）
- 禁止 RuleConfidence 接入执行链
"""

revision = "20260706_1000_feedback_isolation"
down_revision = "20260705_1000_decision_columns"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


def _column_exists(table: str, column: str) -> bool:
    """使用 inspector 检查列是否存在（避免 try/except 吞错）"""
    conn = op.get_bind()
    insp = inspect(conn)
    cols = [c["name"] for c in insp.get_columns(table)]
    return column in cols


def _table_exists(table: str) -> bool:
    """使用 inspector 检查表是否存在"""
    conn = op.get_bind()
    insp = inspect(conn)
    return table in insp.get_table_names()


def upgrade():
    # 1. 新建 feedback_events 表（含幂等约束）
    if not _table_exists("feedback_events"):
        op.create_table(
            "feedback_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("report_id", sa.Integer(), nullable=False),
            sa.Column("rule_id", sa.String(64), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("feedback_type", sa.String(16), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("status", sa.String(16), server_default="submitted"),
            sa.Column("acknowledged_by", sa.Integer(), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_by", sa.Integer(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("resolution_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "report_id", "rule_id", name="uq_feedback_user_report_rule"),
        )
        op.create_index("ix_feedback_events_report_id", "feedback_events", ["report_id"])
        op.create_index("ix_feedback_events_rule_id", "feedback_events", ["rule_id"])
        op.create_index("ix_feedback_events_user_id", "feedback_events", ["user_id"])

    # 2. 给遗留 feedback_records 表添加 status 列（仅当表存在且列不存在时）
    if _table_exists("feedback_records"):
        for col_name, col_type, col_opts in [
            ("status", sa.String(16), {"server_default": "submitted"}),
            ("acknowledged_by", sa.Integer(), {"nullable": True}),
            ("acknowledged_at", sa.DateTime(), {"nullable": True}),
            ("resolved_by", sa.Integer(), {"nullable": True}),
            ("resolved_at", sa.DateTime(), {"nullable": True}),
            ("resolution_note", sa.Text(), {"nullable": True}),
        ]:
            if not _column_exists("feedback_records", col_name):
                op.add_column("feedback_records", sa.Column(col_name, col_type, **col_opts))


def downgrade():
    # 先删除索引，再删除表
    if _table_exists("feedback_events"):
        op.drop_index("ix_feedback_events_user_id", table_name="feedback_events")
        op.drop_index("ix_feedback_events_rule_id", table_name="feedback_events")
        op.drop_index("ix_feedback_events_report_id", table_name="feedback_events")
        op.drop_table("feedback_events")
    # 不删除 feedback_records 的新列（遗留兼容）
