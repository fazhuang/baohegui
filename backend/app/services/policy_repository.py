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

    # Explicit scope isolation: every policy must declare who/what it applies to
    # scope_type: user (current user_id), platform (platform ID), global (explicit only)
    # scope_id: user["sub"], platform_id string, or 'global'
    # These are NOT NULL, indexed, and required by the loader query.
    scope_type = Column(String(16), nullable=False, default="global",
                        comment="user / platform / global — 策略作用域类型")
    scope_id = Column(String(64), nullable=False, default="global",
                      comment="当前 user_id, platform ID, 或 'global' — 策略作用域 ID")

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
    scope_type: str | None = None,
    scope_id: str | None = None,
) -> list[DynamicPolicy]:
    """加载已应用的动态策略 — 执行链唯一入口。

    只返回 status == 'applied' 且 scope 匹配的策略。
    draft / review / approved / rejected / rolled_back 均不返回。

    Scope requirement:
    - scope_type 和 scope_id 必须同时提供；缺失任一 → 返回空列表（fail-closed）
    - tenant policy → scope_type='user', scope_id=str(user["sub"])
    - platform policy → scope_type='platform', scope_id=platform_id
    - global policy → scope_type='global', scope_id='global'（显式创建和审批）

    用法（check.py）:
        from app.services.policy_repository import load_applied_policy_context
        applied_policies = load_applied_policy_context(
            db, policy_type="tenant",
            scope_type="user", scope_id=str(user["sub"]),
        )
        # 将 applied_policies 合并到 DecisionInput 的 tenant_policy
    """
    if not scope_type or not scope_id:
        logger.warning(
            "load_applied_policy_context: scope_type 或 scope_id 缺失 — "
            "无动态策略返回 (fail-closed). scope_type=%r scope_id=%r",
            scope_type, scope_id,
        )
        return []

    policies = (
        db.query(DynamicPolicy)
        .filter(
            DynamicPolicy.status == "applied",
            DynamicPolicy.policy_type == policy_type,
            DynamicPolicy.scope_type == scope_type,
            DynamicPolicy.scope_id == scope_id,
        )
        .all()
    )
    logger.debug(
        "加载 applied 策略: type=%s scope=%s/%s count=%d",
        policy_type, scope_type, scope_id, len(policies),
    )
    return policies


def load_applied_policy_context_all(db: Session) -> dict[str, list[DynamicPolicy]]:
    """加载所有类型的已应用策略 — 需要 scope，不适用于全局查询。

    此函数保留为便捷包装器，但每个调用点必须提供完整的 scope 参数。
    出于 fail-closed 原则，此函数返回空字典（不提供 scope 的全局查询不安全）。
    """
    logger.warning("load_applied_policy_context_all 不支持无 scope 的全局查询，返回空结果")
    return {}


# ═══════════════════════════════════════════════════════════════
# 策略状态变更入口 — 唯一状态写路径
# 所有生产代码只能通过以下函数修改 DynamicPolicy.status。
# 禁止直接赋值 DynamicPolicy.status = ... 或 db.commit()。
# ═══════════════════════════════════════════════════════════════

import json as _json


def _validate_policy_schema(policy_data_str: str) -> tuple[bool, str]:
    """验证 policy_data 是否为合法 JSON。返回 (ok, error_message)。"""
    try:
        parsed = _json.loads(policy_data_str)
        if not isinstance(parsed, dict):
            return False, "policy_data 必须是 JSON 对象"
        return True, ""
    except (_json.JSONDecodeError, TypeError) as e:
        return False, f"policy_data JSON 解析失败: {e}"


def _validate_scope(scope_type: str, scope_id: str) -> tuple[bool, str]:
    """验证 scope_type/scope_id 完整性。"""
    if not isinstance(scope_type, str) or scope_type not in ("user", "platform", "global"):
        return False, f"scope_type 必须是 user/platform/global，收到: {scope_type!r}"
    if not isinstance(scope_id, str) or not scope_id.strip():
        return False, f"scope_id 不能为空，收到: {scope_id!r}"
    return True, ""


def create_draft(
    db: Session,
    policy_key: str,
    policy_type: str,
    policy_data: str,
    scope_type: str,
    scope_id: str,
    created_by: int | None = None,
    description: str | None = None,
) -> DynamicPolicy:
    """创建新的 draft 策略 — 唯一创建入口。"""
    ok, err = _validate_scope(scope_type, scope_id)
    if not ok:
        raise ValueError(err)
    ok, err = _validate_policy_schema(policy_data)
    if not ok:
        raise ValueError(err)

    # 唯一键冲突保护
    existing = db.query(DynamicPolicy).filter(
        DynamicPolicy.policy_key == policy_key
    ).first()
    if existing:
        raise ValueError(f"policy_key '{policy_key}' 已存在")

    policy = DynamicPolicy(
        policy_key=policy_key,
        policy_type=policy_type,
        policy_data=policy_data,
        status="draft",
        scope_type=scope_type,
        scope_id=scope_id,
        created_by=created_by,
        description=description,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    logger.info("创建 draft 策略: id=%d key=%s scope=%s/%s", policy.id, policy_key, scope_type, scope_id)
    return policy


def submit_for_review(db: Session, policy_id: int, admin_id: int) -> DynamicPolicy:
    """提交审批: draft → review。"""
    from app.engine.policy_approval_workflow import policy_approval_workflow
    policy = db.query(DynamicPolicy).filter(DynamicPolicy.id == policy_id).first()
    if not policy:
        raise ValueError(f"策略 id={policy_id} 不存在")
    ok, msg = policy_approval_workflow.submit_for_review(policy)
    if not ok:
        raise ValueError(msg)
    db.commit()
    db.refresh(policy)
    return policy


def approve(db: Session, policy_id: int, admin_id: int, note: str = "") -> DynamicPolicy:
    """审批通过: review → approved。"""
    from app.engine.policy_approval_workflow import policy_approval_workflow
    policy = db.query(DynamicPolicy).filter(DynamicPolicy.id == policy_id).first()
    if not policy:
        raise ValueError(f"策略 id={policy_id} 不存在")
    ok, msg = policy_approval_workflow.approve(policy, admin_id=admin_id, note=note)
    if not ok:
        raise ValueError(msg)
    db.commit()
    db.refresh(policy)
    return policy


def reject(db: Session, policy_id: int, admin_id: int, reason: str = "") -> DynamicPolicy:
    """审批拒绝: review → rejected。"""
    from app.engine.policy_approval_workflow import policy_approval_workflow
    policy = db.query(DynamicPolicy).filter(DynamicPolicy.id == policy_id).first()
    if not policy:
        raise ValueError(f"策略 id={policy_id} 不存在")
    ok, msg = policy_approval_workflow.reject(policy, admin_id=admin_id, note=reason)
    if not ok:
        raise ValueError(msg)
    db.commit()
    db.refresh(policy)
    return policy


def apply(db: Session, policy_id: int, admin_id: int) -> DynamicPolicy:
    """应用策略: approved → applied。

    前置条件验证：
    - 当前状态为 approved
    - approved_by / approved_at 完整
    - policy_data schema 合法
    - scope 完整
    """
    from app.engine.policy_approval_workflow import policy_approval_workflow
    policy = db.query(DynamicPolicy).filter(DynamicPolicy.id == policy_id).first()
    if not policy:
        raise ValueError(f"策略 id={policy_id} 不存在")

    if policy.status != "approved":
        raise ValueError(
            f"策略必须为 approved 状态才能 apply，当前: {policy.status}。"
            f"请完成审批流程后再应用。"
        )
    if not policy.approved_by or not policy.approved_at:
        raise ValueError(
            "策略缺少 approved_by / approved_at，审批记录不完整，拒绝应用。"
        )
    ok, err = _validate_policy_schema(policy.policy_data)
    if not ok:
        raise ValueError(f"策略数据 schema 不合法: {err}")
    ok, err = _validate_scope(policy.scope_type, policy.scope_id)
    if not ok:
        raise ValueError(f"策略 scope 不完整: {err}")

    ok, msg = policy_approval_workflow.apply(policy, admin_id=admin_id)
    if not ok:
        raise ValueError(msg)
    db.commit()
    db.refresh(policy)
    return policy


def rollback(db: Session, policy_id: int, admin_id: int, reason: str = "") -> DynamicPolicy:
    """紧急回滚: applied → rolled_back。"""
    from app.engine.policy_approval_workflow import policy_approval_workflow
    policy = db.query(DynamicPolicy).filter(DynamicPolicy.id == policy_id).first()
    if not policy:
        raise ValueError(f"策略 id={policy_id} 不存在")
    ok, msg = policy_approval_workflow.rollback(policy, admin_id=admin_id, reason=reason)
    if not ok:
        raise ValueError(msg)
    db.commit()
    db.refresh(policy)
    return policy


def revise(db: Session, policy_id: int) -> DynamicPolicy:
    """修订后回到草稿: rejected → draft。"""
    from app.engine.policy_approval_workflow import policy_approval_workflow
    policy = db.query(DynamicPolicy).filter(DynamicPolicy.id == policy_id).first()
    if not policy:
        raise ValueError(f"策略 id={policy_id} 不存在")
    ok, msg = policy_approval_workflow.revise(policy)
    if not ok:
        raise ValueError(msg)
    db.commit()
    db.refresh(policy)
    return policy
