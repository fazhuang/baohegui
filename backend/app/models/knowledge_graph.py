"""知识图谱数据模型"""

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
