"""文档数据模型"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    filename = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_hash = Column(String(64), nullable=False)
    page_count = Column(Integer, nullable=True)
    storage_path = Column(String(512), nullable=False)
    status = Column(
        Enum("uploaded", "parsing", "queued", "checking", "completed", "failed", name="file_status"),
        default="uploaded",
    )
    error_message = Column(Text, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DocumentSection(Base):
    __tablename__ = "document_sections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("uploaded_files.id"), nullable=False)
    section_type = Column(String(64), nullable=False)  # 招标公告, 招标范围, 资格要求, 评审办法, 投标须知
    section_number = Column(String(32), nullable=True)  # 章节编号
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ComplianceReport(Base):
    __tablename__ = "compliance_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("uploaded_files.id"), nullable=False)
    total_score = Column(Float, nullable=False)
    section_score = Column(Float, nullable=True)
    keyword_score = Column(Float, nullable=True)
    forbidden_score = Column(Float, nullable=True)
    semantic_score = Column(Float, nullable=True)
    violation_count = Column(Integer, default=0)
    report_data = Column(Text, nullable=True)  # JSON: DecisionInput + PolicyDecision

    # ── 权威决策列（PolicyKernel v2） ─────────────────────────
    decision_action = Column(String(32), nullable=True)       # pass / warn / require_review / block
    decision_risk_level = Column(String(16), nullable=True)   # low / medium / high / critical
    decision_requires_human_review = Column(Integer, nullable=True)  # 0 or 1
    decision_hash = Column(String(64), nullable=True)
    policy_schema_version = Column(String(16), nullable=True)
    decision_integrity_status = Column(String(32), nullable=True)  # verified / legacy_unverifiable / integrity_failed

    report_pdf_path = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    checked_by = Column(Integer, nullable=True)
