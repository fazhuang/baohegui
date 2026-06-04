"""警示公告数据模型"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.models.document import Base


class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    severity = Column(String(16), nullable=False, default="info")  # info / warning / danger / critical
    category = Column(String(64), nullable=False, default="违规处罚")
    case_date = Column(String(16), nullable=True)  # "2026-06-02"
    summary = Column(Text, nullable=True)
    source = Column(String(128), nullable=True)  # 来源网站
    source_url = Column(String(512), nullable=True)
    is_published = Column(Integer, default=1)  # 0=草稿 1=发布
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
