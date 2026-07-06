"""动态策略持久化模型 + 单一执行加载器

架构：
- DynamicPolicy 持久化策略记录，状态由 PolicyApprovalWorkflow 管理
- 只有 status == applied 的策略被加载器返回
- load_applied_policy_context() 是执行链获取动态策略的唯一入口
- 系统内置默认策略与动态策略严格分离
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import Session

from app.models.document import Base

logger = logging.getLogger(__name__)


class DynamicPolicy(Base):
    """动态策略表 — 审批驱动的策略变更

    状态转换由 PolicyApprovalWorkflow 强制管理。
    只有 applied 状态才会被 load_applied_policy_context() 加载进执行链。
    """

    __tablename__ = "dynamic_policies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_key = Column(String(128), unique=True, nullable=False, comment="策略唯一键")
    policy_type = Column(String(32), nullable=False, default="tenant",
                         comment="tenant / platform / ux — 策略应用层")

    # 策略内容（JSON）
    policy_data = Column(Text, nullable=False, comment="策略内容 JSON")

    # 状态机字段
    status = Column(String(16), default="draft",
                    comment="draft/review/approved/rejected/applied/rolled_back")
    submitted_at = Column(DateTime, nullable=True)
    approved_by = Column(Integer, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approval_note = Column(Text, nullable=True)
    rejected_by = Column(Integer, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    applied_by = Column(Integer, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    rolled_back_by = Column(Integer, nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)
    rollback_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    created_by = Column(Integer, nullable=True, comment="创建者 user_id")
    description = Column(Text, nullable=True, comment="策略描述")


# ═══════════════════════════════════════════════════════════════
# 单一执行加载器
# ═══════════════════════════════════════════════════════════════

def load_applied_policy_context(
    db: Session,
    policy_type: str = "tenant",
) -> list[DynamicPolicy]:
    """加载已应用的动态策略 — 执行链唯一入口。

    只返回 status == 'applied' 的策略。
    draft / review / approved / rejected / rolled_back 均不返回。

    用法（check.py）:
        from app.services.policy_repository import load_applied_policy_context
        applied_policies = load_applied_policy_context(db)
        # 将 applied_policies 合并到 DecisionInput 的 tenant/platform/ux policy
    """
    policies = (
        db.query(DynamicPolicy)
        .filter(
            DynamicPolicy.status == "applied",
            DynamicPolicy.policy_type == policy_type,
        )
        .all()
    )
    logger.debug("加载 applied 策略: type=%s count=%d", policy_type, len(policies))
    return policies


def load_applied_policy_context_all(db: Session) -> dict[str, list[DynamicPolicy]]:
    """加载所有类型的已应用策略"""
    result = {}
    for ptype in ("tenant", "platform", "ux"):
        result[ptype] = load_applied_policy_context(db, policy_type=ptype)
    return result
