"""投诉案例数据模型 — 专为政府采购投诉处理结果公告结构化存储

Phase 2 扩展：
- 审核/发布/抽取/去重/脱敏 14 个新字段
- complaint_types / legal_basis 保持 Text 存储 JSON 字符串（兼容 SQLite）
- decision_date 改为 Date 类型
"""

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Column, Date, DateTime, Float, Integer, String, Text

from app.models.document import Base


class ComplaintCase(Base):
    __tablename__ = "complaint_cases"

    # ── 原有基础字段 ─────────────────────────────────
    id = Column(Integer, primary_key=True, autoincrement=True)
    province = Column(String(32), nullable=False, default="全国")
    source_url = Column(String(512), nullable=True)
    title = Column(String(255), nullable=False)
    project_name = Column(String(255), nullable=True)
    project_number = Column(String(128), nullable=True)
    complainant = Column(Text, nullable=True)
    respondent = Column(Text, nullable=True)
    decision_date = Column(Date, nullable=True)  # Phase 2: Date 类型
    decision_type = Column(String(16), nullable=False, default="unknown")
    complaint_types = Column(Text, nullable=True)  # JSON 数组字符串
    legal_basis = Column(Text, nullable=True)       # JSON 数组字符串
    summary = Column(Text, nullable=True)
    raw_content = Column(Text, nullable=True)
    is_analyzed = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # ── Phase 2: 去重字段 ────────────────────────────
    canonical_url = Column(
        String(1024), nullable=True, comment="权威来源 URL（去重主键）"
    )
    source_type = Column(
        String(32), nullable=True, default="ccgp",
        comment="来源类型: ccgp/mof/province/manual"
    )
    case_no = Column(
        String(128), nullable=True, comment="案件编号"
    )
    city = Column(
        String(64), nullable=True, comment="城市"
    )
    content_hash = Column(
        String(64), nullable=True, comment="内容哈希（SHA256，去重用）"
    )

    # ── Phase 2: 审核/发布状态字段 ──────────────────
    review_status = Column(
        String(32), nullable=True, default="fetched",
        comment="审核状态: fetched/normalized/extracted/pending_review/verified/"
                "published/duplicate/rejected/parse_failed/quarantined/archived"
    )
    publish_status = Column(
        String(16), nullable=True, default="draft",
        comment="发布状态: draft/published/unpublished"
    )

    # ── Phase 2: 脱敏与质量字段 ─────────────────────
    sanitized_content = Column(
        Text, nullable=True, comment="脱敏后内容"
    )
    quality_score = Column(
        Float, nullable=True, default=0.0, comment="质量评分 0.0-1.0"
    )

    # ── Phase 2: 审核审计字段 ────────────────────────
    reviewed_by = Column(Integer, nullable=True, comment="审核人 user_id")
    reviewed_at = Column(DateTime, nullable=True, comment="审核时间")
    published_at = Column(DateTime, nullable=True, comment="发布时间")

    # ── Phase 2: LLM 抽取字段 ───────────────────────
    extractor_version = Column(
        String(32), nullable=True, comment="抽取器版本"
    )
    extraction_metadata = Column(
        Text, nullable=True, comment="抽取元数据 JSON"
    )

    # ── helper methods ──────────────────────────────

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """计算内容 SHA256 哈希"""
        if not content:
            return ""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def set_content_hash(self) -> None:
        """自动计算并设置 content_hash"""
        text = (self.raw_content or "") + (self.summary or "")
        self.content_hash = self.compute_content_hash(text)

    def get_complaint_types(self) -> list[str]:
        """解析 complaint_types JSON"""
        return _parse_json_list(self.complaint_types)

    def set_complaint_types(self, types: list[str]) -> None:
        """设置 complaint_types 为 JSON 字符串"""
        self.complaint_types = json.dumps(types, ensure_ascii=False) if types else None

    def get_legal_basis(self) -> list[str]:
        """解析 legal_basis JSON"""
        return _parse_json_list(self.legal_basis)

    def set_legal_basis(self, basis: list[str]) -> None:
        """设置 legal_basis 为 JSON 字符串"""
        self.legal_basis = json.dumps(basis, ensure_ascii=False) if basis else None

    def get_extraction_metadata(self) -> dict:
        """解析 extraction_metadata JSON"""
        return _parse_json_dict(self.extraction_metadata)

    def set_extraction_metadata(self, meta: dict) -> None:
        """设置 extraction_metadata 为 JSON 字符串"""
        self.extraction_metadata = json.dumps(meta, ensure_ascii=False) if meta else None

    def to_dict(self) -> dict:
        """转为前端友好的 dict"""
        return {
            "id": self.id,
            "province": self.province,
            "source_url": self.source_url,
            "canonical_url": self.canonical_url,
            "source_type": self.source_type,
            "title": self.title,
            "project_name": self.project_name,
            "project_number": self.project_number,
            "case_no": self.case_no,
            "city": self.city,
            "complainant": self.complainant,
            "respondent": self.respondent,
            "decision_date": self.decision_date.isoformat() if self.decision_date else None,
            "decision_type": self.decision_type,
            "complaint_types": self.get_complaint_types(),
            "legal_basis": self.get_legal_basis(),
            "summary": self.summary,
            "raw_content": self.raw_content,
            "sanitized_content": self.sanitized_content,
            "content_hash": self.content_hash,
            "review_status": self.review_status,
            "publish_status": self.publish_status,
            "quality_score": self.quality_score,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "extractor_version": self.extractor_version,
            "is_analyzed": self.is_analyzed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_public_dict(self) -> dict:
        """转为公开可见的 dict（隐藏敏感字段 + 审核/脱敏前内容）"""
        d = self.to_dict()
        # 公开视图：不暴露 raw_content（仅展示 sanitized_content）
        d.pop("raw_content", None)
        d.pop("reviewed_by", None)
        d.pop("reviewed_at", None)
        d.pop("extraction_metadata", None)
        # 公开视图：不暴露投诉人和被投诉人身份
        d.pop("complainant", None)
        d.pop("respondent", None)
        d["content"] = d.pop("sanitized_content", None) or d.get("summary", "")
        return d


# ── module-level helpers ────────────────────────────

def _parse_json_list(raw: str | None) -> list[str]:
    """安全解析 JSON 数组字符串"""
    if not raw or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if item and str(item).strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    # 兼容旧 Python repr 格式
    import ast
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if item and str(item).strip()]
        except (ValueError, SyntaxError, TypeError):
            pass
    return [raw.strip("[]'\" \t\n\r")] if raw.strip("[]'\" \t\n\r") else []


def _parse_json_dict(raw: str | None) -> dict:
    """安全解析 JSON 对象字符串"""
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return {}
