"""知识图谱数据模型

v3 新增 rule_id, source_url, jurisdiction, effective_date, publish_date, metadata_json 字段
"""

from datetime import datetime, timezone

from sqlalchemy import Column, Date, DateTime, Float, Integer, String, Text, ForeignKey, Index

from app.models.document import Base


class KGNode(Base):
    """知识图谱节点"""
    __tablename__ = "kg_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_type = Column(String(32), nullable=False)  # regulation / case / rule / template
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=False)
    source = Column(String(256), default="")  # 来源
    source_url = Column(String(1024), default="", comment="来源 URL")
    tags = Column(String(512), default="")  # 逗号分隔的标签

    # ── v3 关联与管辖字段 ──────────────────────────────
    rule_id = Column(
        String(64),
        nullable=True,
        index=True,
        comment="关联的系统规则 ID（如 R001）",
    )
    jurisdiction = Column(
        String(128),
        default="",
        comment="管辖范围/平台（如 全国/甘肃/广东/财政部）",
    )
    effective_date = Column(Date, nullable=True, comment="生效日期")
    publish_date = Column(Date, nullable=True, comment="发布日期")
    metadata_json = Column(
        Text,
        default="{}",
        comment="扩展元数据 JSON（如法规条文编号、案件编号等）",
    )

    # ── v2 可信与审计字段 ──────────────────────────────
    trust_level = Column(
        Float,
        nullable=False,
        default=0.5,
        index=True,
        comment="可信度评分 0.0-1.0，默认 0.5（未验证）",
    )
    audit_status = Column(
        String(16),
        nullable=False,
        default="unreviewed",
        index=True,
        comment="审核状态: unreviewed / verified / flagged / rejected",
    )
    audited_by = Column(Integer, nullable=True, comment="审核人 user_id")
    audited_at = Column(DateTime, nullable=True, comment="审核时间")

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_kg_nodes_type_status", "node_type", "audit_status"),
        Index("ix_kg_nodes_type_trust", "node_type", "trust_level"),
    )


class KGEdge(Base):
    """知识图谱边"""
    __tablename__ = "kg_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("kg_nodes.id"), nullable=False)
    target_id = Column(Integer, ForeignKey("kg_nodes.id"), nullable=False)
    relation = Column(String(64), nullable=False)  # references / violates / cites / satisfies
    weight = Column(Float, default=1.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
