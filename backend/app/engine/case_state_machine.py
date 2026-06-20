"""案例运营状态机

Phase 2 — 定义并强制 11 种状态的合法转换：
  fetched → normalized → extracted → pending_review → verified → published
                                                                    ↓
  parse_failed ← (any parser stage)                    unpublished (下架)
  duplicate (any stage, by dedup)                      ↓
  rejected (review)                                    archived
  quarantined (review/admin)

所有非法状态转换必须被拒绝并记录。
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CaseStatus(str, Enum):
    """案例生命周期状态"""
    FETCHED = "fetched"              # 已抓取，待规范化
    NORMALIZED = "normalized"        # 已规范化（字段清洗完成）
    EXTRACTED = "extracted"          # 已 LLM 结构化抽取
    PENDING_REVIEW = "pending_review"  # 待人工审核
    VERIFIED = "verified"            # 审核通过，待发布
    PUBLISHED = "published"          # 已发布
    UNPUBLISHED = "unpublished"      # 已下架
    DUPLICATE = "duplicate"          # 去重判定为重复
    REJECTED = "rejected"            # 审核拒绝
    PARSE_FAILED = "parse_failed"    # 解析/抽取失败
    QUARANTINED = "quarantined"      # 隔离（内容存疑/需再确认）
    ARCHIVED = "archived"            # 归档（下架后/过期）


# ── 合法转换表 ───────────────────────────────────────
# 格式：源状态 → 允许到达的目标状态集合
VALID_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.FETCHED: {
        CaseStatus.NORMALIZED,
        CaseStatus.DUPLICATE,
        CaseStatus.PARSE_FAILED,
    },
    CaseStatus.NORMALIZED: {
        CaseStatus.EXTRACTED,
        CaseStatus.PARSE_FAILED,
        CaseStatus.DUPLICATE,
    },
    CaseStatus.EXTRACTED: {
        CaseStatus.PENDING_REVIEW,
        CaseStatus.PARSE_FAILED,
        CaseStatus.DUPLICATE,
    },
    CaseStatus.PENDING_REVIEW: {
        CaseStatus.VERIFIED,
        CaseStatus.REJECTED,
        CaseStatus.QUARANTINED,
    },
    CaseStatus.VERIFIED: {
        CaseStatus.PUBLISHED,
        CaseStatus.QUARANTINED,
    },
    CaseStatus.PUBLISHED: {
        CaseStatus.UNPUBLISHED,
        CaseStatus.ARCHIVED,
    },
    CaseStatus.UNPUBLISHED: {
        CaseStatus.PUBLISHED,      # 重新发布
        CaseStatus.ARCHIVED,
    },
    CaseStatus.DUPLICATE: {
        CaseStatus.FETCHED,        # 重新处理（误判恢复）
    },
    CaseStatus.REJECTED: {
        CaseStatus.FETCHED,        # 重新处理（修正后重试）
    },
    CaseStatus.PARSE_FAILED: {
        CaseStatus.FETCHED,        # 重试
    },
    CaseStatus.QUARANTINED: {
        CaseStatus.FETCHED,        # 重新处理
        CaseStatus.ARCHIVED,       # 确认废弃
    },
    CaseStatus.ARCHIVED: set(),    # 终态
}

# 额外：unpublished 是 publish_status 字段的值
# 和 review_status 的 PUBLISHED/UNPUBLISHED 协同


class CaseStatusStateMachine:
    """案例审核状态机

    用法:
        sm = CaseStatusStateMachine()
        sm.transition(case, CaseStatus.NORMALIZED, user_id=123)
    """

    @staticmethod
    def can_transition(
        from_status: Optional[str],
        to_status: str,
    ) -> bool:
        """检查状态转换是否合法"""
        if not from_status:
            from_status = CaseStatus.FETCHED.value

        try:
            current = CaseStatus(from_status)
            target = CaseStatus(to_status)
        except ValueError:
            logger.warning(f"非法状态值: from={from_status}, to={to_status}")
            return False

        allowed = VALID_TRANSITIONS.get(current, set())
        return target in allowed

    @staticmethod
    def transition(
        case,
        to_status: str,
        user_id: Optional[int] = None,
        note: str = "",
    ) -> tuple[bool, str]:
        """执行状态转换，返回 (success, message)

        case 必须有 review_status 属性（ComplaintCase 或兼容对象）。
        非法转换将返回 (False, error_message)。
        """
        from_status = getattr(case, "review_status", None)
        if not from_status:
            from_status = CaseStatus.FETCHED.value

        if not CaseStatusStateMachine.can_transition(from_status, to_status):
            msg = (
                f"非法状态转换: {from_status} → {to_status}。"
                f"允许从 {from_status} 转换到: "
                f"{CaseStatusStateMachine.get_allowed_transitions(from_status)}"
            )
            logger.warning(msg)
            return False, msg

        case.review_status = to_status

        # 转换钩子
        if to_status == CaseStatus.VERIFIED.value:
            from datetime import datetime, timezone
            if user_id:
                case.reviewed_by = user_id
            case.reviewed_at = datetime.now(timezone.utc)

        if to_status == CaseStatus.PUBLISHED.value:
            from datetime import datetime, timezone
            case.publish_status = "published"
            case.published_at = datetime.now(timezone.utc)

        if to_status == CaseStatus.UNPUBLISHED.value:
            case.publish_status = "unpublished"

        if to_status == CaseStatus.REJECTED.value:
            from datetime import datetime, timezone
            if user_id:
                case.reviewed_by = user_id
            case.reviewed_at = datetime.now(timezone.utc)

        logger.info(
            f"状态转换: case_id={getattr(case, 'id', '?')} "
            f"{from_status} → {to_status}"
            f"{' by user=' + str(user_id) if user_id else ''}"
        )
        return True, f"{from_status} → {to_status}"

    @staticmethod
    def get_allowed_transitions(current_status: str) -> list[str]:
        """获取当前状态允许转换到的目标状态列表"""
        try:
            current = CaseStatus(current_status)
        except ValueError:
            return []
        return [s.value for s in VALID_TRANSITIONS.get(current, set())]


# ── 发布状态枚举 ─────────────────────────────────────

class PublishStatus(str, Enum):
    DRAFT = "draft"             # 草稿
    PUBLISHED = "published"     # 已发布
    UNPUBLISHED = "unpublished"  # 已下架
