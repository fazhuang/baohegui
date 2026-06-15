"""知识图谱数据模型

v2 新增 trust_level, audit_status, audited_by, audited_at 字段
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, ForeignKey

from app.models.document import Base


class KGNode(Base):
    """知识图谱节点"""
    __tablename__ = "kg_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_type = Column(String(32), nullable=False)  # regulation / case / rule / template
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=False)
    source = Column(String(256), default="")  # 来源
    tags = Column(String(512), default="")  # 逗号分隔的标签

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


class KGEdge(Base):
    """知识图谱边"""
    __tablename__ = "kg_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("kg_nodes.id"), nullable=False)
    target_id = Column(Integer, ForeignKey("kg_nodes.id"), nullable=False)
    relation = Column(String(64), nullable=False)  # references / violates / cites / satisfies
    weight = Column(Float, default=1.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
