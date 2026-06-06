"""审查反馈服务 — 用户误报标记、规则置信度调整、管理员告警"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Session

from app.models.document import Base

logger = logging.getLogger(__name__)

# ── 扩展表注册到 DocumentBase，便于 init_db() 统一创建 ──
# 在 database.py 的 init_db() 中也会注册此 Base


class FeedbackRecord(Base):
    """反馈记录表"""

    __tablename__ = "feedback_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, nullable=False)
    rule_id = Column(String(64), nullable=False)
    user_id = Column(Integer, nullable=False)
    feedback_type = Column(String(16), nullable=False)  # confirm / false_positive / missed
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RuleConfidence(Base):
    """规则置信度表"""

    __tablename__ = "rule_confidences"

    rule_id = Column(String(64), primary_key=True)
    base_confidence = Column(Float, default=1.0)  # 基准置信度
    current_confidence = Column(Float, default=1.0)  # 当前置信度
    total_feedbacks = Column(Integer, default=0)
    false_positive_count = Column(Integer, default=0)
    confirm_count = Column(Integer, default=0)
    needs_review = Column(Integer, default=0)  # 0=正常, 1=待审核
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class FeedbackService:
    """反馈处理服务"""

    # 置信度调整参数
    CONFIRM_BOOST = 0.02  # 每次确认 +2%
    FALSE_POSITIVE_PENALTY = 0.05  # 每次误报 -5%
    FP_REVIEW_THRESHOLD = 3  # 累积3次误报 → 待审核
    MIN_CONFIDENCE = 0.5  # 最低置信度
    MAX_CONFIDENCE = 1.0

    # 误报率告警阈值（超过此比例触发管理员告警）
    FP_RATE_ALERT_THRESHOLD = 0.3

    @staticmethod
    def submit_feedback(
        db: Session,
        report_id: int,
        rule_id: str,
        user_id: int,
        feedback_type: str,  # "confirm" / "false_positive" / "missed"
        comment: Optional[str] = None,
    ) -> dict:
        """提交反馈并更新规则置信度"""
        if feedback_type not in ("confirm", "false_positive", "missed"):
            raise ValueError(f"无效的反馈类型: {feedback_type}")

        # 保存反馈记录
        record = FeedbackRecord(
            report_id=report_id,
            rule_id=rule_id,
            user_id=user_id,
            feedback_type=feedback_type,
            comment=comment,
        )
        db.add(record)

        # 更新规则置信度
        confidence = (
            db.query(RuleConfidence).filter(RuleConfidence.rule_id == rule_id).first()
        )

        if not confidence:
            confidence = RuleConfidence(rule_id=rule_id)
            db.add(confidence)
            db.flush()  # 确保 default 列值生效

        confidence.total_feedbacks = (confidence.total_feedbacks or 0) + 1

        if feedback_type == "confirm":
            confidence.confirm_count = (confidence.confirm_count or 0) + 1
            confidence.current_confidence = min(
                FeedbackService.MAX_CONFIDENCE,
                (confidence.current_confidence or 1.0) + FeedbackService.CONFIRM_BOOST,
            )
        elif feedback_type == "false_positive":
            confidence.false_positive_count = (confidence.false_positive_count or 0) + 1
            confidence.current_confidence = max(
                FeedbackService.MIN_CONFIDENCE,
                (confidence.current_confidence or 1.0) - FeedbackService.FALSE_POSITIVE_PENALTY,
            )

        # 检查是否需要标记为待审核
        if (confidence.false_positive_count or 0) >= FeedbackService.FP_REVIEW_THRESHOLD:
            if confidence.needs_review == 0:
                confidence.needs_review = 1
                logger.warning(
                    "规则 %s 累积 %d 次误报，已标记为待审核",
                    rule_id,
                    confidence.false_positive_count,
                )

        # 检查误报率是否超过阈值
        total = confidence.total_feedbacks or 0
        fp_count = confidence.false_positive_count or 0
        if total > 0:
            fp_rate = fp_count / total
            if fp_rate >= FeedbackService.FP_RATE_ALERT_THRESHOLD:
                logger.warning(
                    "规则 %s 误报率 %.0f%% 超过告警阈值，建议管理员审查",
                    rule_id,
                    fp_rate * 100,
                )

        confidence.updated_at = datetime.now(timezone.utc)
        db.commit()

        return {
            "rule_id": rule_id,
            "current_confidence": confidence.current_confidence,
            "total_feedbacks": confidence.total_feedbacks,
            "needs_review": confidence.needs_review == 1,
            "message": "反馈已记录，置信度已更新",
        }

    @staticmethod
    def get_rule_confidence(db: Session, rule_id: str) -> Optional[dict]:
        """获取规则当前的置信度信息"""
        conf = (
            db.query(RuleConfidence).filter(RuleConfidence.rule_id == rule_id).first()
        )
        if not conf:
            return None
        return {
            "rule_id": conf.rule_id,
            "current_confidence": conf.current_confidence,
            "base_confidence": conf.base_confidence,
            "total_feedbacks": conf.total_feedbacks,
            "false_positive_count": conf.false_positive_count,
            "confirm_count": conf.confirm_count,
            "needs_review": conf.needs_review == 1,
        }

    @staticmethod
    def get_rules_needing_review(db: Session) -> list[dict]:
        """获取所有需要管理员审核的规则"""
        confs = (
            db.query(RuleConfidence).filter(RuleConfidence.needs_review == 1).all()
        )
        return [
            {
                "rule_id": c.rule_id,
                "false_positive_count": c.false_positive_count,
                "current_confidence": c.current_confidence,
            }
            for c in confs
        ]


feedback_service = FeedbackService()
