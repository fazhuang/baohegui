"""规则数据模型"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Rule(Base):
    """内部规则"""

    __tablename__ = "rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(String(64), unique=True, nullable=False)  # 如 SEC-001
    rule_type = Column(
        String(32), nullable=False
    )  # chapter_required / keyword_required / forbidden / semantic
    target = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    weight = Column(Float, default=10.0)
    category = Column(String(64), default="base")  # base / platform / industry / custom
    law_ref = Column(Text, nullable=True)  # 法规引用
    suggestion = Column(Text, nullable=True)  # 整改建议
    enabled = Column(Boolean, default=True)
    version = Column(String(16), default="1.0")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class RuleMapping(Base):
    """内部规则与平台规则的映射"""

    __tablename__ = "rule_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(String(64), ForeignKey("rules.rule_id"), nullable=False)
    platform = Column(String(128), nullable=False)  # 平台名称
    platform_code = Column(String(64), nullable=False)  # 平台规则代码
    platform_desc = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RuleVersion(Base):
    """规则版本追踪"""

    __tablename__ = "rule_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(16), nullable=False)
    change_log = Column(Text, nullable=True)
    rule_count = Column(Integer, default=0)
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
