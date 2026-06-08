"""投诉案例数据模型 — 专为政府采购投诉处理结果公告结构化存储"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.models.document import Base


class ComplaintCase(Base):
    __tablename__ = "complaint_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    province = Column(String(32), nullable=False, default="全国")  # 省份
    source_url = Column(String(512), nullable=True)  # 原文链接
    title = Column(String(255), nullable=False)  # 公告标题
    project_name = Column(String(255), nullable=True)  # 采购项目名称
    project_number = Column(String(128), nullable=True)  # 项目编号
    complainant = Column(Text, nullable=True)  # 投诉人
    respondent = Column(Text, nullable=True)  # 被投诉人
    decision_date = Column(String(16), nullable=True)  # 处理决定日期
    decision_type = Column(String(16), nullable=False, default="unknown")  # upheld(成立) / rejected(驳回) / partial(部分成立) / dismissed(驳回)
    complaint_types = Column(Text, nullable=True)  # 投诉类型（JSON数组）
    legal_basis = Column(Text, nullable=True)  # 法规依据（JSON数组）
    summary = Column(Text, nullable=True)  # 摘要
    raw_content = Column(Text, nullable=True)  # 原始公告全文（Markdown）
    is_analyzed = Column(Integer, default=0)  # 0=未分析 1=已分析 2=已提炼规则
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
