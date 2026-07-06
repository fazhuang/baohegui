"""动态策略持久化模型 + 单一执行加载器

架构：
- DynamicPolicy 持久化策略记录，状态由 PolicyApprovalWorkflow 管理
- 只有 status == applied 的策略被加载器返回
- load_applied_policy_context() 是执行链获取动态策略的唯一入口
- 系统内置默认策略与动态策略严格分离
- 策略状态变更与审计日志在同一数据库事务中原子写入
"""

from __future__ import annotations

import hashlib
import json
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
    scope_type = Column(String(16), nullable=False,
                        comment="user / platform / global — 策略作用域类型")
    scope_id = Column(String(64), nullable=False,
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

    # Enforce: applied policy must pass schema validation at load time.
    # Historical illegal applied policies are logged and excluded from execution.
    # Also enforce scope/policy_type pairing at load time — defense in depth.
    valid_policies = []
    for dp in policies:
        try:
            _validate_policy_data_strict(dp.policy_type, dp.policy_data)
            ok, err = _validate_scope(dp.policy_type, dp.scope_type, dp.scope_id)
            if not ok:
                logger.error(
                    "非法 applied policy scope 被拒绝进入执行链: id=%d key=%s error=%s. "
                    "请回滚并修订此策略。",
                    dp.id, dp.policy_key, err,
                )
                continue
            valid_policies.append(dp)
        except ValueError as e:
            logger.error(
                "非法 applied policy 被拒绝进入执行链: id=%d key=%s error=%s. "
                "请回滚并修订此策略。",
                dp.id, dp.policy_key, e,
            )

    logger.debug(
        "加载 applied 策略: type=%s scope=%s/%s total=%d valid=%d",
        policy_type, scope_type, scope_id, len(policies), len(valid_policies),
    )
    return valid_policies


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

def _validate_policy_data_strict(policy_type: str, policy_data_str: str) -> str:
    """使用严格 Pydantic schema 验证 policy_data，返回规范化 JSON 字符串。

    严禁仅检查"是否为 JSON 对象"。
    所有阶段 (create_draft, apply, loader) 均调用此验证。
    """
    from app.services.policy_schema import validate_policy_data, normalize_policy_data
    validate_policy_data(policy_type, policy_data_str)
    return normalize_policy_data(policy_type, policy_data_str)


def _validate_scope(policy_type: str, scope_type: str, scope_id: str) -> tuple[bool, str]:
    """验证 scope_type/scope_id 完整性以及 policy_type/scope_type 配对。

    合法组合：
    - tenant + user + 非空 user id     (用户级租户策略)
    - platform + platform + 非空 platform id (平台级策略)

    禁止组合：
    - tenant + platform (任何 scope_id)
    - platform + user (任何 scope_id)
    - global scope（当前不支持）
    - 空 scope_id
    """
    if not isinstance(scope_type, str) or scope_type not in ("user", "platform", "global"):
        return False, f"scope_type 必须是 user/platform/global，收到: {scope_type!r}"
    if not isinstance(scope_id, str) or not scope_id.strip():
        return False, f"scope_id 不能为空，收到: {scope_id!r}"

    # policy_type/scope_type 配对验证
    if policy_type == "tenant" and scope_type == "platform":
        return False, "tenant 策略不能使用 platform scope，请使用 user 或 global"
    if policy_type == "platform" and scope_type == "user":
        return False, "platform 策略不能使用 user scope，请使用 platform 或 global"

    # Reject global scope — not supported in this iteration.
    if scope_type == "global":
        return False, "global scope 策略暂不支持。当前仅支持 user 和 platform scope。"

    return True, ""


# ═══════════════════════════════════════════════════════════════
# 原子审计写入
# ═══════════════════════════════════════════════════════════════

def _write_policy_audit(
    db: Session,
    user_id: int,
    action: str,
    policy: DynamicPolicy,
    from_status: str,
    to_status: str,
    note: str = "",
) -> None:
    """在同一事务中写入 policy 审计日志。

    Policy 状态变更属于强制安全审计，不检查 audit_log_enabled。
    审计失败 → 事务回滚 → policy 状态也不生效。
    审计 detail 不包含完整 policy_data，只记录 hash + scope + 状态转换。
    """
    from app.core.audit import AuditLog

    policy_fields_hash = hashlib.sha256(
        policy.policy_data.encode("utf-8")
    ).hexdigest()[:16] if policy.policy_data else "none"

    detail = json.dumps({
        "policy_key": policy.policy_key,
        "policy_type": policy.policy_type,
        "scope_type": policy.scope_type,
        "scope_id": policy.scope_id,
        "from_status": from_status,
        "to_status": to_status,
        "note": note,
        "policy_data_hash": policy_fields_hash,
    }, ensure_ascii=False)

    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource="dynamic_policy",
        resource_id=str(policy.id),
        detail=detail,
    )
    db.add(entry)
    logger.debug("policy audit written: action=%s policy_id=%d %s→%s", action, policy.id, from_status, to_status)


# ═══════════════════════════════════════════════════════════════
# 内部：每个操作必须在同一 try 块内完成 transition → audit → commit。分三步走。
# 策略状态变更函数 — 每个函数原子写入策略 + 审计
# ═══════════════════════════════════════════════════════════════

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
    ok, err = _validate_scope(policy_type, scope_type, scope_id)
    if not ok:
        raise ValueError(err)
    from app.services.policy_schema import is_supported_policy_type
    if not is_supported_policy_type(policy_type):
        raise ValueError(
            f"不支持的 policy_type: {policy_type!r}。当前仅支持 tenant 和 platform。"
        )
    try:
        normalized_data = _validate_policy_data_strict(policy_type, policy_data)
    except ValueError as e:
        raise ValueError(f"policy_data 验证失败: {e}")

    existing = db.query(DynamicPolicy).filter(
        DynamicPolicy.policy_key == policy_key
    ).first()
    if existing:
        raise ValueError(f"policy_key '{policy_key}' 已存在")

    policy = DynamicPolicy(
        policy_key=policy_key,
        policy_type=policy_type,
        policy_data=normalized_data,
        status="draft",
        scope_type=scope_type,
        scope_id=scope_id,
        created_by=created_by,
        description=description,
    )
    db.add(policy)
    db.flush()  # get policy.id for audit

    try:
        _write_policy_audit(
            db, user_id=created_by or 0, action="policy_create",
            policy=policy, from_status="", to_status="draft",
        )
    except Exception:
        db.rollback()
        raise

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(policy)
    logger.info("创建 draft 策略: id=%d key=%s scope=%s/%s", policy.id, policy_key, scope_type, scope_id)
    return policy


# ═══════════════════════════════════════════════════════════════
# 内部：每个操作必须在同一 try 块内完成 transition → audit → commit。
# audit 必须在 transition 之前写入；audit 失败 → 整个操作失败 → policy 不回滚。
# 任何阶段异常 → db.rollback() → policy 内存状态不改变。
# ═══════════════════════════════════════════════════════════════

def _do_state_change(
    db: Session,
    policy_id: int,
    transition_fn,
    admin_id: int,
    audit_action: str,
    to_status: str,
    note: str = "",
) -> DynamicPolicy:
    """Execute a state transition with atomic audit.

    Order:
    1. load policy
    2. validate preconditions
    3. write audit record FIRST (so audit failure → policy untouched)
    4. transition policy state
    5. single commit (audit + policy)
    6. on any failure → rollback
    """
    from app.engine.policy_approval_workflow import policy_approval_workflow

    policy = db.query(DynamicPolicy).filter(DynamicPolicy.id == policy_id).first()
    if not policy:
        raise ValueError(f"策略 id={policy_id} 不存在")

    try:
        from_status = policy.status

        # ── Precondition checks (before any mutation) ──
        if to_status == "applied":
            if policy.status != "approved":
                raise ValueError(
                    f"策略必须为 approved 状态才能 apply，当前: {policy.status}。"
                    f"请完成审批流程后再应用。"
                )
            if not policy.approved_by or not policy.approved_at:
                raise ValueError(
                    "策略缺少 approved_by / approved_at，审批记录不完整，拒绝应用。"
                )
            try:
                _validate_policy_data_strict(policy.policy_type, policy.policy_data)
            except ValueError as e:
                raise ValueError(f"策略数据 schema 不合法: {e}")
            ok_s, err_s = _validate_scope(policy.policy_type, policy.scope_type, policy.scope_id)
            if not ok_s:
                raise ValueError(f"策略 scope 不完整: {err_s}")

        # ── Audit FIRST: if this fails, policy is untouched ──
        _write_policy_audit(
            db, user_id=admin_id, action=audit_action,
            policy=policy, from_status=from_status, to_status=to_status, note=note,
        )

        # ── Transition: mutate only after audit succeeds ──
        ok, msg = transition_fn(policy)
        if not ok:
            raise ValueError(msg)

        # ── Single commit for both ──
        db.commit()
        db.refresh(policy)
        return policy

    except ValueError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def submit_for_review(db: Session, policy_id: int, admin_id: int) -> DynamicPolicy:
    """提交审批: draft → review。"""
    from app.engine.policy_approval_workflow import policy_approval_workflow
    return _do_state_change(
        db, policy_id,
        transition_fn=lambda p: policy_approval_workflow.submit_for_review(p),
        admin_id=admin_id, audit_action="policy_submit", to_status="review",
    )


def approve(db: Session, policy_id: int, admin_id: int, note: str = "") -> DynamicPolicy:
    """审批通过: review → approved。"""
    from app.engine.policy_approval_workflow import policy_approval_workflow
    return _do_state_change(
        db, policy_id,
        transition_fn=lambda p: policy_approval_workflow.approve(p, admin_id=admin_id, note=note),
        admin_id=admin_id, audit_action="policy_approve", to_status="approved", note=note,
    )


def reject(db: Session, policy_id: int, admin_id: int, reason: str = "") -> DynamicPolicy:
    """审批拒绝: review → rejected。"""
    from app.engine.policy_approval_workflow import policy_approval_workflow
    return _do_state_change(
        db, policy_id,
        transition_fn=lambda p: policy_approval_workflow.reject(p, admin_id=admin_id, note=reason),
        admin_id=admin_id, audit_action="policy_reject", to_status="rejected", note=reason,
    )


def apply(db: Session, policy_id: int, admin_id: int) -> DynamicPolicy:
    """应用策略: approved → applied（此后影响执行链）。"""
    from app.engine.policy_approval_workflow import policy_approval_workflow
    return _do_state_change(
        db, policy_id,
        transition_fn=lambda p: policy_approval_workflow.apply(p, admin_id=admin_id),
        admin_id=admin_id, audit_action="policy_apply", to_status="applied",
    )


def rollback(db: Session, policy_id: int, admin_id: int, reason: str = "") -> DynamicPolicy:
    """紧急回滚: applied → rolled_back。"""
    from app.engine.policy_approval_workflow import policy_approval_workflow
    return _do_state_change(
        db, policy_id,
        transition_fn=lambda p: policy_approval_workflow.rollback(p, admin_id=admin_id, reason=reason),
        admin_id=admin_id, audit_action="policy_rollback", to_status="rolled_back", note=reason,
    )


def revise(db: Session, policy_id: int, admin_id: int) -> DynamicPolicy:
    """修订后回到草稿: rejected → draft。"""
    from app.engine.policy_approval_workflow import policy_approval_workflow
    return _do_state_change(
        db, policy_id,
        transition_fn=lambda p: policy_approval_workflow.revise(p),
        admin_id=admin_id, audit_action="policy_revise", to_status="draft",
    )
