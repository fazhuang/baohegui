"""审计日志服务"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, Text, create_engine
from sqlalchemy.orm import declarative_base, Session

from .config import settings

logger = logging.getLogger(__name__)

AuditBase = declarative_base()


class AuditLog(AuditBase):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    action = Column(Text, nullable=False)
    resource = Column(Text, nullable=True)
    resource_id = Column(Text, nullable=True)
    detail = Column(Text, nullable=True)
    ip_address = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AuditService:
    def __init__(self, db_url: Optional[str] = None):
        self.enabled = settings.audit_log_enabled
        if self.enabled:
            self.engine = create_engine(db_url or settings.database_url)
            AuditBase.metadata.create_all(self.engine)

    def log(
        self,
        user_id: int,
        action: str,
        resource: Optional[str] = None,
        resource_id: Optional[str] = None,
        detail: Optional[dict] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return
        try:
            with Session(self.engine) as session:
                entry = AuditLog(
                    user_id=user_id,
                    action=action,
                    resource=resource,
                    resource_id=resource_id,
                    detail=json.dumps(detail, ensure_ascii=False) if detail else None,
                    ip_address=ip_address,
                )
                session.add(entry)
                session.commit()
        except Exception as e:
            logger.error(f"审计日志写入失败: {e}")

    def query(self, user_id: Optional[int] = None, limit: int = 100) -> list[dict]:
        if not self.enabled:
            return []
        with Session(self.engine) as session:
            query = session.query(AuditLog)
            if user_id:
                query = query.filter(AuditLog.user_id == user_id)
            rows = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
            return [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "action": r.action,
                    "resource": r.resource,
                    "resource_id": r.resource_id,
                    "detail": r.detail,
                    "ip_address": r.ip_address,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]


audit_service = AuditService()
