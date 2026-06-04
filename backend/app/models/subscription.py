"""订阅与配额数据模型"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Float

from app.models.document import Base


class UserQuota(Base):
    """用户月度配额"""
    __tablename__ = "user_quotas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    plan = Column(String(16), default="free")  # free / pro / enterprise
    period_key = Column(String(7), nullable=False)  # "2026-06"

    # 文件数配额
    files_limit = Column(Integer, default=5)
    files_used = Column(Integer, default=0)

    # Token 配额
    tokens_limit = Column(Integer, default=50000)
    tokens_used = Column(Integer, default=0)

    # 费用配额（元）
    cost_limit_yuan = Column(Float, default=5.0)
    cost_used_yuan = Column(Float, default=0.0)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# 配额默认值（按计划）
PLAN_QUOTAS = {
    "free": {
        "files_limit": 5,
        "tokens_limit": 50000,
        "cost_limit_yuan": 5.0,
    },
    "pro": {
        "files_limit": 100,
        "tokens_limit": 1000000,
        "cost_limit_yuan": 100.0,
    },
    "enterprise": {
        "files_limit": 999999,
        "tokens_limit": 10000000,
        "cost_limit_yuan": 1000.0,
    },
}
