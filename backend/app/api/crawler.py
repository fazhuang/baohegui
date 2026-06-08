"""案例采集 API 路由 — 手动触发 + 状态查看 + 规则分析"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.crawler_service import count_cases, query_cases
from app.services.rule_miner import analyze_all_unanalyzed
from app.services.sync_scheduler import sync_scheduler

router = APIRouter(prefix="/api/crawler", tags=["crawler"])


@router.post("/trigger")
async def trigger_crawl():
    """手动触发一轮案例采集"""
    record = await sync_scheduler.scrape_cases()
    return {
        "status": record.status.value,
        "error": record.error_message or None,
        "finished_at": record.finished_at,
    }


@router.get("/status")
async def crawler_status():
    """采集器状态"""
    return sync_scheduler.get_status()


@router.get("/cases")
async def list_cases(
    province: str = Query("", description="按省份筛选"),
    decision_type: str = Query("", description="按决定类型筛选: upheld/rejected/partial"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """已采集案例列表（分页）"""
    cases = query_cases(
        db, province=province, decision_type=decision_type,
        limit=limit, offset=offset,
    )
    total = count_cases(db)
    return {
        "items": [
            {
                "id": c.id,
                "title": c.title,
                "province": c.province,
                "project_name": c.project_name,
                "decision_type": c.decision_type,
                "decision_date": c.decision_date,
                "complaint_types": c.complaint_types,
                "source_url": c.source_url,
                "is_analyzed": c.is_analyzed,
                "created_at": str(c.created_at),
            }
            for c in cases
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/cases/{case_id}")
async def get_case_detail(case_id: int, db: Session = Depends(get_db)):
    """单条案例详情"""
    from app.models.complaint_case import ComplaintCase

    case = db.query(ComplaintCase).filter(ComplaintCase.id == case_id).first()
    if not case:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="案例不存在")
    return {
        "id": case.id,
        "province": case.province,
        "source_url": case.source_url,
        "title": case.title,
        "project_name": case.project_name,
        "project_number": case.project_number,
        "complainant": case.complainant,
        "respondent": case.respondent,
        "decision_date": case.decision_date,
        "decision_type": case.decision_type,
        "complaint_types": case.complaint_types,
        "legal_basis": case.legal_basis,
        "summary": case.summary,
        "raw_content": case.raw_content,
        "is_analyzed": case.is_analyzed,
        "created_at": str(case.created_at),
    }


@router.post("/analyze")
async def trigger_analysis(db: Session = Depends(get_db)):
    """手动触发现规则分析"""
    result = analyze_all_unanalyzed(db)
    return result


@router.get("/stats")
async def case_stats(db: Session = Depends(get_db)):
    """案例统计"""
    return count_cases(db)
