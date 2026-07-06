"""候选规则数据模型 — 强制审核状态转换

不变量：
- 仅 pending → approved/rejected/duplicate
- rejected、duplicate、approved 均不得再次 approve
- promote 必须是两阶段操作：先审核通过，再升级
- 禁止直接调用模型方法绕过转换校验
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# ── 合法审核转换表 ─────────────────────────────────────
VALID_REVIEW_TRANSITIONS = {
    "pending": {"approved", "rejected", "duplicate"},
    "approved": set(),      # 终态，不可再变
    "rejected": set(),      # 终态，不可再变
    "duplicate": set(),     # 终态，不可再变
}


class CandidateRule(Base):
    """候选规则 — 需人工审核后才能进入正式规则库

    两阶段操作:
    1. approve — pending → approved（审核）
    2. promote_candidate_to_rule — approved → 正式规则（升级）

    禁止在一次调用中同时完成审核和升级。
    """

    __tablename__ = "candidate_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(
        String(64), unique=True, nullable=False, comment="候选规则 ID"
    )
    source_case_id = Column(Integer, nullable=True, comment="关联投诉案例 ID")
    source_type = Column(String(32), default="miner", comment="来源: miner/manual/llm")
    rule_type = Column(String(32), nullable=False, comment="规则类型")
    target = Column(String(255), nullable=False, comment="检测目标")
    description = Column(Text, nullable=False, comment="规则描述")
    risk_level = Column(String(16), default="medium", comment="风险等级: critical/high/medium/low")
    category = Column(String(64), default="candidate", comment="规则类别")
    law_ref = Column(Text, nullable=True, comment="法规引用")
    suggestion = Column(Text, nullable=True, comment="整改建议")
    pattern = Column(Text, nullable=True, comment="匹配模式 regex")
    evidence_snippets = Column(Text, nullable=True, comment="证据片段 JSON")
    confidence = Column(Float, default=0.0, comment="挖掘置信度 0.0-1.0")
    miner_version = Column(String(32), nullable=True, comment="矿机版本")
    review_status = Column(String(16), default="pending",
                           comment="审核状态: pending/approved/rejected/duplicate")
    reviewed_by = Column(Integer, nullable=True, comment="审核人 user_id")
    reviewed_at = Column(DateTime, nullable=True, comment="审核时间")
    review_note = Column(Text, nullable=True, comment="审核意见")
    promoted_to = Column(String(64), nullable=True, comment="升级为正式规则 ID")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    @property
    def is_approved(self) -> bool:
        return self._resolve_review_status() == "approved"

    @property
    def is_pending(self) -> bool:
        return self._resolve_review_status() == "pending"

    def _resolve_review_status(self) -> str:
        """解析真实审核状态 — Column default 在持久化前为 None"""
        return self.review_status or "pending"

    @property
    def is_promotable(self) -> bool:
        """是否可以升级为正式规则"""
        return (
            self._resolve_review_status() == "approved"
            and self.reviewed_by is not None
            and self.reviewed_at is not None
            and not self.promoted_to
        )

    def approve(self, reviewer_id: int, note: str = "") -> None:
        """审核通过 — 仅 pending → approved"""
        current = self._resolve_review_status()
        if current != "pending":
            raise ValueError(
                f"仅 pending 状态的候选规则可审核，当前状态: {current}"
            )
        now = datetime.now(timezone.utc)
        self.review_status = "approved"
        self.reviewed_by = reviewer_id
        self.reviewed_at = now
        self.review_note = note

    def reject(self, reviewer_id: int, note: str = "") -> None:
        """审核拒绝 — 仅 pending → rejected"""
        current = self._resolve_review_status()
        if current != "pending":
            raise ValueError(
                f"仅 pending 状态的候选规则可拒绝，当前状态: {current}"
            )
        self.review_status = "rejected"
        self.reviewed_by = reviewer_id
        self.reviewed_at = datetime.now(timezone.utc)
        self.review_note = note

    def mark_duplicate(self, reviewer_id: int, note: str = "") -> None:
        """标记为重复 — 仅 pending → duplicate"""
        current = self._resolve_review_status()
        if current != "pending":
            raise ValueError(
                f"仅 pending 状态的候选规则可标记重复，当前状态: {current}"
            )
        self.review_status = "duplicate"
        self.reviewed_by = reviewer_id
        self.reviewed_at = datetime.now(timezone.utc)
        self.review_note = note

    def mark_promoted(self, promoted_rule_id: str) -> None:
        """标记为已升级 — 仅 approved（未升级）可调用"""
        current = self._resolve_review_status()
        if current != "approved":
            raise ValueError(
                f"仅 approved 状态的候选规则可升级，当前状态: {current}"
            )
        if self.promoted_to:
            raise ValueError(f"候选规则已升级为 {self.promoted_to}，不可重复升级")
        self.promoted_to = promoted_rule_id
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "source_case_id": self.source_case_id,
            "source_type": self.source_type,
            "rule_type": self.rule_type,
            "target": self.target,
            "description": self.description,
            "risk_level": self.risk_level,
            "category": self.category,
            "law_ref": self.law_ref,
            "suggestion": self.suggestion,
            "pattern": self.pattern,
            "confidence": self.confidence,
            "miner_version": self.miner_version,
            "review_status": self.review_status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "review_note": self.review_note,
            "promoted_to": self.promoted_to,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
