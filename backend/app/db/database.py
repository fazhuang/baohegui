"""数据库连接管理"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.audit import AuditBase
from app.core.config import settings
from app.models.announcement import Base as AnnouncementBase
from app.models.document import Base as DocumentBase
from app.models.rule import Base as RuleBase
from app.models.subscription import Base as SubscriptionBase


def _get_engine_kwargs(url: str) -> dict:
    """根据数据库类型返回 engine 配置参数"""
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = NullPool
    return kwargs


engine = create_engine(settings.database_url, **_get_engine_kwargs(settings.database_url))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """初始化所有表"""
    # 延迟导入以确保表类注册到对应 Base.metadata
    from app.services.feedback_service import FeedbackRecord, RuleConfidence  # noqa: F401
    from app.models.knowledge_graph import KGNode, KGEdge  # noqa: F401

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
