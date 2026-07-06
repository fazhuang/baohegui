"""Policy Approval Workflow — 策略变更必须通过审批状态机

强制执行：
- 任何改变执行链行为的策略变更必须经过审批
- 只有 applied 状态影响执行链
- rejected → draft 回环（修订后重新提交）
- 紧急回滚：applied → rolled_back

模式参考：CaseStatusStateMachine (engine/case_state_machine.py)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class PolicyApprovalStatus(str, Enum):
    """策略审批状态"""
    DRAFT = "draft"              # 草稿，编辑中
    REVIEW = "review"            # 已提交，待管理员审批
    APPROVED = "approved"         # 审批通过，待应用
    REJECTED = "rejected"         # 审批拒绝，需修订
    APPLIED = "applied"           # 已应用到生产（影响执行链）
    ROLLED_BACK = "rolled_back"  # 紧急回滚


# ── 合法转换表 ───────────────────────────────────────
VALID_TRANSITIONS: dict[PolicyApprovalStatus, set[PolicyApprovalStatus]] = {
    PolicyApprovalStatus.DRAFT: {
        PolicyApprovalStatus.REVIEW,
    },
    PolicyApprovalStatus.REVIEW: {
        PolicyApprovalStatus.APPROVED,
        PolicyApprovalStatus.REJECTED,
    },
    PolicyApprovalStatus.REJECTED: {
        PolicyApprovalStatus.DRAFT,  # 修订后重新提交
    },
    PolicyApprovalStatus.APPROVED: {
        PolicyApprovalStatus.APPLIED,
        PolicyApprovalStatus.DRAFT,  # 放弃应用，回到草稿
    },
    PolicyApprovalStatus.APPLIED: {
        PolicyApprovalStatus.ROLLED_BACK,  # 紧急回滚
    },
    PolicyApprovalStatus.ROLLED_BACK: {
        PolicyApprovalStatus.DRAFT,  # 修复后重新走流程
    },
}

# 终态集合（不能再转换到其他状态）
TERMINAL_STATUSES = set()

# 影响执行链的状态 — 只有这些状态下的策略会被 PolicyKernel 加载
EXECUTION_AFFECTING = {PolicyApprovalStatus.APPLIED}


class PolicyApprovalWorkflow:
    """策略审批工作流

    用法:
        wf = PolicyApprovalWorkflow()

        # 提交审批
        ok, msg = wf.submit_for_review(policy_record)

        # 审批通过
        ok, msg = wf.approve(policy_record, admin_id=1)

        # 应用到生产
        ok, msg = wf.apply(policy_record, admin_id=1)

        # 紧急回滚
        ok, msg = wf.rollback(policy_record, admin_id=1, reason="...")

    关键不变量：
    - 只有 status == applied 的策略才被 PolicyKernel 加载
    - 任何 bypass 审批的行为（直接改 applied）必须被 code review 拒绝
    """

    @staticmethod
    def can_transition(
        from_status: Optional[str],
        to_status: str,
    ) -> bool:
        """检查状态转换是否合法"""
        if not from_status:
            from_status = PolicyApprovalStatus.DRAFT.value

        try:
            current = PolicyApprovalStatus(from_status)
            target = PolicyApprovalStatus(to_status)
        except ValueError:
            logger.warning(f"非法策略审批状态值: from={from_status}, to={to_status}")
            return False

        allowed = VALID_TRANSITIONS.get(current, set())
        return target in allowed

    @staticmethod
    def submit_for_review(record) -> tuple[bool, str]:
        """提交审批: draft → review"""
        return PolicyApprovalWorkflow._transition(
            record, PolicyApprovalStatus.REVIEW.value, admin_id=None
        )

    @staticmethod
    def approve(record, admin_id: int, note: str = "") -> tuple[bool, str]:
        """审批通过: review → approved"""
        return PolicyApprovalWorkflow._transition(
            record, PolicyApprovalStatus.APPROVED.value,
            admin_id=admin_id, note=note,
        )

    @staticmethod
    def reject(record, admin_id: int, note: str = "") -> tuple[bool, str]:
        """审批拒绝: review → rejected"""
        return PolicyApprovalWorkflow._transition(
            record, PolicyApprovalStatus.REJECTED.value,
            admin_id=admin_id, note=note,
        )

    @staticmethod
    def apply(record, admin_id: int) -> tuple[bool, str]:
        """应用到生产: approved → applied（此后影响执行链）"""
        return PolicyApprovalWorkflow._transition(
            record, PolicyApprovalStatus.APPLIED.value,
            admin_id=admin_id,
        )

    @staticmethod
    def rollback(record, admin_id: int, reason: str = "") -> tuple[bool, str]:
        """紧急回滚: applied → rolled_back（此后不再影响执行链）"""
        return PolicyApprovalWorkflow._transition(
            record, PolicyApprovalStatus.ROLLED_BACK.value,
            admin_id=admin_id, note=f"ROLLBACK: {reason}",
        )

    @staticmethod
    def revise(record) -> tuple[bool, str]:
        """修订后回到草稿: rejected → draft"""
        return PolicyApprovalWorkflow._transition(
            record, PolicyApprovalStatus.DRAFT.value, admin_id=None
        )

    @staticmethod
    def get_allowed_transitions(current_status: str) -> list[str]:
        """获取当前状态允许转换到的目标状态列表"""
        try:
            current = PolicyApprovalStatus(current_status)
        except ValueError:
            return []
        return [s.value for s in VALID_TRANSITIONS.get(current, set())]

    @staticmethod
    def affects_execution(status: str) -> bool:
        """检查该状态是否影响执行链"""
        try:
            s = PolicyApprovalStatus(status)
        except ValueError:
            return False
        return s in EXECUTION_AFFECTING

    # ── 内部 ──────────────────────────────────────────

    @staticmethod
    def _transition(
        record,
        to_status: str,
        admin_id: Optional[int] = None,
        note: str = "",
    ) -> tuple[bool, str]:
        """执行状态转换，返回 (success, message)

        record 必须有 status 属性。
        """
        from_status = getattr(record, "status", PolicyApprovalStatus.DRAFT.value)

        if not PolicyApprovalWorkflow.can_transition(from_status, to_status):
            msg = (
                f"非法策略审批状态转换: {from_status} → {to_status}。"
                f"允许从 {from_status} 转换到: "
                f"{PolicyApprovalWorkflow.get_allowed_transitions(from_status)}"
            )
            logger.warning(msg)
            return False, msg

        record.status = to_status

        # 转换钩子
        now = datetime.now(timezone.utc)

        if to_status == PolicyApprovalStatus.REVIEW.value:
            if hasattr(record, "submitted_at"):
                record.submitted_at = now

        if to_status == PolicyApprovalStatus.APPROVED.value:
            if hasattr(record, "approved_by"):
                record.approved_by = admin_id
            if hasattr(record, "approved_at"):
                record.approved_at = now
            if hasattr(record, "approval_note"):
                record.approval_note = note

        if to_status == PolicyApprovalStatus.REJECTED.value:
            if hasattr(record, "rejected_by"):
                record.rejected_by = admin_id
            if hasattr(record, "rejected_at"):
                record.rejected_at = now
            if hasattr(record, "rejection_reason"):
                record.rejection_reason = note

        if to_status == PolicyApprovalStatus.APPLIED.value:
            if hasattr(record, "applied_by"):
                record.applied_by = admin_id
            if hasattr(record, "applied_at"):
                record.applied_at = now
            logger.warning(
                f"策略已应用: policy_id={getattr(record, 'id', '?')} — 此后影响执行链"
            )

        if to_status == PolicyApprovalStatus.ROLLED_BACK.value:
            if hasattr(record, "rolled_back_by"):
                record.rolled_back_by = admin_id
            if hasattr(record, "rolled_back_at"):
                record.rolled_back_at = now
            if hasattr(record, "rollback_reason"):
                record.rollback_reason = note
            logger.warning(
                f"策略已回滚: policy_id={getattr(record, 'id', '?')} — 此后不再影响执行链. 原因: {note}"
            )

        logger.info(
            f"策略审批状态转换: policy_id={getattr(record, 'id', '?')} "
            f"{from_status} → {to_status}"
            f"{' by admin=' + str(admin_id) if admin_id else ''}"
        )
        return True, f"{from_status} → {to_status}"


# ── 全局单例 ─────────────────────────────────────────

policy_approval_workflow = PolicyApprovalWorkflow()
