"""反馈状态机 — 反馈只写入，不参与执行链

强制执行：
- feedback_event 只写入 feedback_records + rule_confidences，不修改 rule / LLM prompt / 排序
- 状态转换由管理员审核驱动，不自动生效
- 任何试图从 feedback 读数据进入执行链的代码，code review 时直接拒绝

模式参考：CaseStatusStateMachine (engine/case_state_machine.py)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class FeedbackStatus(str, Enum):
    """反馈生命周期状态"""
    SUBMITTED = "submitted"         # 用户提交，待管理员查看
    ACKNOWLEDGED = "acknowledged"   # 管理员已确认，待处理
    RESOLVED = "resolved"           # 已处理（规则已修正等）
    CLOSED = "closed"                # 关闭（无需处理/误报确认）


# ── 合法转换表 ───────────────────────────────────────
VALID_TRANSITIONS: dict[FeedbackStatus, set[FeedbackStatus]] = {
    FeedbackStatus.SUBMITTED: {
        FeedbackStatus.ACKNOWLEDGED,
        FeedbackStatus.CLOSED,  # 明显误报可直接关闭
    },
    FeedbackStatus.ACKNOWLEDGED: {
        FeedbackStatus.RESOLVED,
        FeedbackStatus.CLOSED,
    },
    FeedbackStatus.RESOLVED: {
        FeedbackStatus.CLOSED,
    },
    FeedbackStatus.CLOSED: set(),  # 终态
}


class FeedbackStateMachine:
    """反馈审核状态机

    用法:
        sm = FeedbackStateMachine()
        ok, msg = sm.transition(feedback_record, FeedbackStatus.ACKNOWLEDGED, admin_id=1)

    关键约束：状态转换是纯管理操作。无论状态如何变化，feedback 数据
    绝不回流到执行链（rule_engine / llm_engine / fusion / policy_kernel）。
    """

    @staticmethod
    def can_transition(
        from_status: Optional[str],
        to_status: str,
    ) -> bool:
        """检查状态转换是否合法"""
        if not from_status:
            from_status = FeedbackStatus.SUBMITTED.value

        try:
            current = FeedbackStatus(from_status)
            target = FeedbackStatus(to_status)
        except ValueError:
            logger.warning(f"非法反馈状态值: from={from_status}, to={to_status}")
            return False

        allowed = VALID_TRANSITIONS.get(current, set())
        return target in allowed

    @staticmethod
    def transition(
        record,  # FeedbackRecord or compatible object with status attribute
        to_status: str,
        admin_id: Optional[int] = None,
        note: str = "",
    ) -> tuple[bool, str]:
        """执行状态转换，返回 (success, message)

        record 必须有 status 属性（FeedbackRecord 或兼容对象）。
        非法转换将返回 (False, error_message)。
        """
        from_status = getattr(record, "status", None)
        if not from_status:
            # 新提交的反馈默认从 submitted 开始
            from_status = FeedbackStatus.SUBMITTED.value
            if hasattr(record, "status"):
                record.status = from_status

        if not FeedbackStateMachine.can_transition(from_status, to_status):
            msg = (
                f"非法反馈状态转换: {from_status} → {to_status}。"
                f"允许从 {from_status} 转换到: "
                f"{FeedbackStateMachine.get_allowed_transitions(from_status)}"
            )
            logger.warning(msg)
            return False, msg

        record.status = to_status

        # 转换钩子
        if to_status == FeedbackStatus.ACKNOWLEDGED.value:
            if hasattr(record, "acknowledged_by"):
                record.acknowledged_by = admin_id
            if hasattr(record, "acknowledged_at"):
                record.acknowledged_at = datetime.now(timezone.utc)

        if to_status == FeedbackStatus.RESOLVED.value:
            if hasattr(record, "resolved_by"):
                record.resolved_by = admin_id
            if hasattr(record, "resolved_at"):
                record.resolved_at = datetime.now(timezone.utc)
            if hasattr(record, "resolution_note"):
                record.resolution_note = note

        logger.info(
            f"反馈状态转换: feedback_id={getattr(record, 'id', '?')} "
            f"{from_status} → {to_status}"
            f"{' by admin=' + str(admin_id) if admin_id else ''}"
        )
        return True, f"{from_status} → {to_status}"

    @staticmethod
    def get_allowed_transitions(current_status: str) -> list[str]:
        """获取当前状态允许转换到的目标状态列表"""
        try:
            current = FeedbackStatus(current_status)
        except ValueError:
            return []
        return [s.value for s in VALID_TRANSITIONS.get(current, set())]

    # ── 隔离守卫：禁止 feedback 进入执行链 ──────────────

    # 这些方法故意不存在：
    #   get_confidence_for_rule()   — 执行链不应查询 RuleConfidence
    #   adjust_rule_weight()        — feedback 不应修改规则权重
    #   filter_llm_prompt()         — feedback 不应过滤 LLM 输入
    #   reorder_violations()        — feedback 不应影响输出排序
    #
    # RuleConfidence 表仅用于管理面板展示，不被任何引擎读取。
    # 如需根据置信度调整规则，必须通过 PolicyApprovalWorkflow 审批。


# ── 全局单例 ─────────────────────────────────────────

feedback_state_machine = FeedbackStateMachine()
