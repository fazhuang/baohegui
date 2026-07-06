"""审查反馈服务 — 不可变事件日志

架构约束：
- FeedbackEvent 是只写不可变事件日志
- RuleConfidence 保留为只读聚合表（仅供管理面板展示）
- submit_feedback() 绝不修改规则权重、置信度、启用状态、LLM prompt、排序、candidate 或 policy
- 反馈聚合统计仅在管理查询中从 FeedbackEvent 计算
- 带验证的 submit 入口必须接收 validated_rule_ids 或验证后的上下文
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.document import Base

logger = logging.getLogger(__name__)


class FeedbackEvent(Base):
    """反馈事件表 — 不可变事件日志

    幂等约束：同一 (user_id, report_id, rule_id) 只能有一条记录。
    状态由 FeedbackStateMachine 管理，管理员执行转换。
    """

    __tablename__ = "feedback_events"
    __table_args__ = (
        UniqueConstraint("user_id", "report_id", "rule_id", name="uq_feedback_user_report_rule"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, nullable=False, index=True)
    rule_id = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    feedback_type = Column(String(16), nullable=False)  # confirm / false_positive / missed
    comment = Column(Text, nullable=True)
    # 状态机字段
    status = Column(String(16), default="submitted")  # submitted/acknowledged/resolved/closed
    acknowledged_by = Column(Integer, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_by = Column(Integer, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RuleConfidence(Base):
    """规则置信度表 — 只读聚合视图

    WARNING: 此表仅供管理面板展示，绝不接入执行链。
    置信度数据来自 FeedbackEvent 的离线聚合，不由 submit_feedback 实时更新。
    """

    __tablename__ = "rule_confidences"

    rule_id = Column(String(64), primary_key=True)
    base_confidence = Column(Float, default=1.0)
    current_confidence = Column(Float, default=1.0)
    total_feedbacks = Column(Integer, default=0)
    false_positive_count = Column(Integer, default=0)
    confirm_count = Column(Integer, default=0)
    needs_review = Column(Integer, default=0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def _extract_rule_ids_from_report(report_data: dict) -> set[str]:
    """从 report_data 中提取所有合法的 rule_id — fail-closed: 无数据返回空集合。

    共享函数：API 层和 FeedbackService 都使用此函数进行验证。
    """
    ids: set[str] = set()
    di = report_data.get("_decision_input", {}) if isinstance(report_data, dict) else {}

    for rv in di.get("rule_violations", []):
        if isinstance(rv, dict):
            rid = rv.get("rule_id")
            if rid:
                ids.add(rid)
    for bf in di.get("bias_findings", []):
        if isinstance(bf, dict):
            pid = bf.get("pattern_id")
            if pid:
                ids.add(f"BIAS-{pid}")

    violations = report_data.get("violations", [])
    if isinstance(violations, list):
        for v in violations:
            if isinstance(v, dict):
                rid = v.get("rule_id")
                if rid:
                    ids.add(rid)

    return ids


class FeedbackService:
    """反馈事件服务 — 只写不可变事件

    职责边界：
    ✅ 写入 FeedbackEvent（幂等，数据库级唯一约束）
    ✅ 查询 FeedbackEvent（管理面板用途）
    ✅ submit_feedback_with_validation 提供带绑定的安全入口
    ❌ 修改 RuleConfidence
    ❌ 修改规则权重、启用状态
    ❌ 影响 LLM prompt、排序、candidate、policy
    """

    @staticmethod
    def _persist_feedback_event(
        db: Session,
        report_id: int,
        rule_id: str,
        user_id: int,
        feedback_type: str,
        comment: Optional[str] = None,
    ) -> dict:
        """私有持久化函数 — 不验证 report/rule 绑定。

        幂等：同一 (user_id, report_id, rule_id) 已存在时返回 duplicate。
        不修改 RuleConfidence。

        **仅可由 FeedbackService.submit_feedback_with_validation 调用。**
        禁止从 API、其他 service 或测试直接调用。
        """
        if feedback_type not in ("confirm", "false_positive", "missed"):
            raise ValueError(f"无效的反馈类型: {feedback_type}")

        event = FeedbackEvent(
            report_id=report_id,
            rule_id=rule_id,
            user_id=user_id,
            feedback_type=feedback_type,
            comment=comment,
            status="submitted",
        )
        db.add(event)

        try:
            db.commit()
            db.refresh(event)
        except IntegrityError:
            db.rollback()
            existing = (
                db.query(FeedbackEvent)
                .filter(
                    FeedbackEvent.user_id == user_id,
                    FeedbackEvent.report_id == report_id,
                    FeedbackEvent.rule_id == rule_id,
                )
                .first()
            )
            return {
                "rule_id": rule_id,
                "status": "duplicate",
                "message": "对此报告的此规则已提交过反馈，不可重复提交",
                "existing_id": existing.id if existing else None,
            }

        logger.info(
            "反馈事件已记录: id=%d report_id=%d rule_id=%s type=%s user=%d",
            event.id, report_id, rule_id, feedback_type, user_id,
        )

        return {
            "rule_id": rule_id,
            "event_id": event.id,
            "status": "submitted",
            "message": "反馈已记录",
        }

    @staticmethod
    def submit_feedback_with_validation(
        db: Session,
        report_id: int,
        rule_id: str,
        user_id: int,
        feedback_type: str,
        report_data: dict,
        comment: Optional[str] = None,
    ) -> dict:
        """安全反馈入口 — 验证 rule_id 属于报告后再写入

        验证规则（fail-closed）：
        - report_data 必须可解析
        - 必须能从中提取 valid_rule_ids
        - rule_id 必须在 valid_rule_ids 中
        - 不满足任一条件 → ValueError
        """
        # 验证 rule_id 有效性
        valid_rule_ids = _extract_rule_ids_from_report(report_data)
        if not valid_rule_ids:
            raise ValueError("此报告不包含可反馈的审查发现")
        if rule_id not in valid_rule_ids:
            raise ValueError(f"rule_id '{rule_id}' 不存在于此报告的审查结果中")

        return FeedbackService._persist_feedback_event(
            db=db,
            report_id=report_id,
            rule_id=rule_id,
            user_id=user_id,
            feedback_type=feedback_type,
            comment=comment,
        )

    @staticmethod
    def get_rule_confidence(db: Session, rule_id: str) -> Optional[dict]:
        """获取规则置信度 — 管理面板专用，绝不接入执行链"""
        events = (
            db.query(FeedbackEvent)
            .filter(FeedbackEvent.rule_id == rule_id)
            .all()
        )
        if not events:
            return None

        total = len(events)
        fp_count = sum(1 for e in events if e.feedback_type == "false_positive")
        confirm_count = sum(1 for e in events if e.feedback_type == "confirm")

        return {
            "rule_id": rule_id,
            "total_feedbacks": total,
            "false_positive_count": fp_count,
            "confirm_count": confirm_count,
            "source": "aggregated_from_feedback_events",
        }

    @staticmethod
    def get_rules_needing_review(db: Session) -> list[dict]:
        """获取误报率高的规则 — 管理面板专用"""
        from collections import Counter
        fp_by_rule: Counter = Counter()
        total_by_rule: Counter = Counter()
        for event in db.query(FeedbackEvent).all():
            total_by_rule[event.rule_id] += 1
            if event.feedback_type == "false_positive":
                fp_by_rule[event.rule_id] += 1

        result = []
        for rule_id, total in total_by_rule.items():
            fp = fp_by_rule.get(rule_id, 0)
            if fp >= 3:
                result.append({
                    "rule_id": rule_id,
                    "false_positive_count": fp,
                    "total_feedbacks": total,
                })
        return result


# 保留旧名称兼容（内部引用）
FeedbackRecord = FeedbackEvent

feedback_service = FeedbackService()
