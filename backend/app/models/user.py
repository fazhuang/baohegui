"""用户数据模型"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Boolean

from .document import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    hashed_password = Column(String(128), nullable=False)
    role = Column(String(16), default="user")  # admin / user
    company = Column(String(128), nullable=True)
    email = Column(String(128), nullable=True)
    is_active = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False)
    verification_code = Column(String(6), nullable=True)
    verification_code_expires_at = Column(DateTime, nullable=True)
    password_reset_token = Column(String(64), nullable=True)
    password_reset_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
