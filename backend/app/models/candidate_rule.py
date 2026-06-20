"""候选规则数据模型

Phase 2 — 候选规则工作流：
- 规则矿机产出候选规则 → candidate_rules 表
- 候选规则必须经人工审核（pending → approved/rejected/duplicate）
- 审核通过后才能进入版本化规则资产（promoted_to）
- 禁止直接热加载生产规则
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class CandidateRule(Base):
    """候选规则 — 需人工审核后才能进入正式规则库"""

    __tablename__ = "candidate_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(
        String(64), unique=True, nullable=False, comment="候选规则 ID"
    )
    source_case_id = Column(
        Integer, nullable=True, comment="关联投诉案例 ID"
    )
    source_type = Column(
        String(32), default="miner",
        comment="来源: miner/manual/llm"
    )
    rule_type = Column(
        String(32), nullable=False, comment="规则类型"
    )
    target = Column(
        String(255), nullable=False, comment="检测目标"
    )
    description = Column(
        Text, nullable=False, comment="规则描述"
    )
    risk_level = Column(
        String(16), default="medium",
        comment="风险等级: critical/high/medium/low"
    )
    category = Column(
        String(64), default="candidate", comment="规则类别"
    )
    law_ref = Column(Text, nullable=True, comment="法规引用")
    suggestion = Column(Text, nullable=True, comment="整改建议")
    pattern = Column(Text, nullable=True, comment="匹配模式 regex")
    evidence_snippets = Column(
        Text, nullable=True, comment="证据片段 JSON"
    )
    confidence = Column(
        Float, default=0.0, comment="挖掘置信度 0.0-1.0"
    )
    miner_version = Column(
        String(32), nullable=True, comment="矿机版本"
    )
    review_status = Column(
        String(16), default="pending",
        comment="审核状态: pending/approved/rejected/duplicate"
    )
    reviewed_by = Column(Integer, nullable=True, comment="审核人 user_id")
    reviewed_at = Column(DateTime, nullable=True, comment="审核时间")
    review_note = Column(Text, nullable=True, comment="审核意见")
    promoted_to = Column(
        String(64), nullable=True, comment="升级为正式规则 ID"
    )
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_approved(self) -> bool:
        return self.review_status == "approved"

    @property
    def is_pending(self) -> bool:
        return self.review_status == "pending"

    def approve(self, reviewer_id: int, note: str = "", promoted_to: str = "") -> None:
        """审核通过"""
        self.review_status = "approved"
        self.reviewed_by = reviewer_id
        self.reviewed_at = datetime.now(timezone.utc)
        self.review_note = note
        self.promoted_to = promoted_to or self.candidate_id

    def reject(self, reviewer_id: int, note: str = "") -> None:
        """审核拒绝"""
        self.review_status = "rejected"
        self.reviewed_by = reviewer_id
        self.reviewed_at = datetime.now(timezone.utc)
        self.review_note = note

    def mark_duplicate(self, reviewer_id: int, note: str = "") -> None:
        """标记为重复"""
        self.review_status = "duplicate"
        self.reviewed_by = reviewer_id
        self.reviewed_at = datetime.now(timezone.utc)
        self.review_note = note

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
