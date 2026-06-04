"""数据库连接管理"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.audit import AuditBase
from app.models.announcement import Base as AnnouncementBase
from app.models.document import Base as DocumentBase
from app.models.rule import Base as RuleBase
from app.models.subscription import Base as SubscriptionBase

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """初始化所有表"""
    DocumentBase.metadata.create_all(bind=engine)
    RuleBase.metadata.create_all(bind=engine)
    AuditBase.metadata.create_all(bind=engine)
    AnnouncementBase.metadata.create_all(bind=engine)
    SubscriptionBase.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
