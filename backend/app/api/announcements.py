"""警示公告 API"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.announcement import Announcement
from app.services.announcement_service import seed_announcements

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


def _ensure_seeded(db: Session) -> None:
    """确保公告表有数据"""
    try:
        seed_announcements(db)
    except Exception:
        pass


@router.get("")
async def list_announcements(
    limit: int = Query(5, ge=1, le=50),
    severity: str | None = Query(None, description="筛选 severity"),
    db: Session = Depends(get_db),
):
    """获取最新公告列表"""
    _ensure_seeded(db)

    query = db.query(Announcement).filter(Announcement.is_published == 1)
    if severity:
        query = query.filter(Announcement.severity == severity)

    announcements = (
        query.order_by(Announcement.case_date.desc(), Announcement.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "total": len(announcements),
        "announcements": [
            {
                "id": a.id,
                "title": a.title,
                "severity": a.severity,
                "category": a.category,
                "case_date": a.case_date,
                "summary": a.summary,
                "source": a.source,
            }
            for a in announcements
        ],
    }
