"""案例采集 API 路由 — 手动触发 + 状态查看 + 规则分析

安全基线：管理操作（trigger/analyze）仅管理员可访问。
读取端点（cases/stats）仍需要认证但普通用户可用。

Phase 1：案例数据分级
- 普通用户案例列表不返回敏感字段（complainant、respondent）。
- 普通用户案例详情不返回 raw_content、complainant、respondent。
- 管理员案例详情返回完整信息并写入审计日志。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.audit import audit_service
from app.core.security import get_current_user, require_admin
from app.db.database import get_db
from app.services.crawler_service import count_cases, query_cases, count_case_stats
from app.services.rule_miner import analyze_all_unanalyzed
from app.services.sync_scheduler import sync_scheduler

router = APIRouter(prefix="/api/crawler", tags=["crawler"])


@router.post("/trigger")
async def trigger_crawl(admin: dict = Depends(require_admin)):
    """手动触发一轮案例采集 — 仅管理员

    返回各来源新增案例数、KG 同步数量、错误列表。
    """
    record = await sync_scheduler.scrape_cases()
    audit_service.log(
        user_id=int(admin["sub"]),
        action="crawler_trigger",
        resource="crawler",
        detail={
            "status": record.status.value,
            "error": record.error_message or None,
            "finished_at": str(record.finished_at) if record.finished_at else None,
            "scrape_stats": record.scrape_stats,
        },
    )
    return {
        "status": record.status.value,
        "error": record.error_message or None,
        "finished_at": record.finished_at,
        "scrape_stats": record.scrape_stats,
    }


@router.get("/status")
async def crawler_status(user: dict = Depends(get_current_user)):
    """采集器状态 — 含最后一次采集摘要和 KG 同步摘要"""
    status = sync_scheduler.get_status()

    # 从 history 中提取上次采集和 KG 同步的完整摘要
    last_scrape = status.get("last_case_scrape")

    # 构建 KG 同步摘要（从最后一次成功的采集统计中提取）
    kg_sync_summary = None
    if last_scrape and last_scrape.get("scrape_stats"):
        kg_sync_summary = {
            "last_synced_count": last_scrape["scrape_stats"].get("kg_synced", 0),
            "last_scrape_cases_saved": last_scrape["scrape_stats"].get("cases_saved", 0),
        }

    status["kg_sync_summary"] = kg_sync_summary
    return status


@router.get("/cases")
async def list_cases(
    province: str = Query("", description="按省份筛选"),
    decision_type: str = Query("", description="按决定类型筛选: upheld/rejected/partial"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """已采集案例列表（分页）"""
    cases = query_cases(
        db, province=province, decision_type=decision_type,
        limit=limit, offset=offset,
    )
    total = count_cases(db, province=province, decision_type=decision_type)
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
async def get_case_detail(case_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """单条案例详情 — Phase 1 数据分级：

    - 管理员：返回完整信息（含 raw_content、complainant、respondent），记录审计日志。
    - 普通用户：不返回 raw_content、complainant、respondent。
    """
    from app.models.complaint_case import ComplaintCase

    case = db.query(ComplaintCase).filter(ComplaintCase.id == case_id).first()
    if not case:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="案例不存在")

    is_admin = user.get("role") == "admin"

    if is_admin:
        audit_service.log(
            user_id=int(user["sub"]),
            action="crawler_case_detail_admin",
            resource="complaint_case",
            resource_id=str(case_id),
            detail={"title": case.title, "province": case.province},
        )

    base = {
        "id": case.id,
        "province": case.province,
        "source_url": case.source_url,
        "title": case.title,
        "project_name": case.project_name,
        "project_number": case.project_number,
        "decision_date": case.decision_date,
        "decision_type": case.decision_type,
        "complaint_types": case.complaint_types,
        "legal_basis": case.legal_basis,
        "summary": case.summary,
        "is_analyzed": case.is_analyzed,
        "created_at": str(case.created_at),
    }
    if is_admin:
        base["complainant"] = case.complainant
        base["respondent"] = case.respondent
        base["raw_content"] = case.raw_content
    return base


@router.post("/analyze")
async def trigger_analysis(db: Session = Depends(get_db), admin: dict = Depends(require_admin)):
    """手动触发规则分析 — 仅管理员"""
    result = analyze_all_unanalyzed(db)
    # Compute candidate rule count from actual returned structure
    candidate_rules = sum(
        1 for v in result.get("new_pattern_candidates", {}).values()
        if v.get("is_new")
    )
    audit_service.log(
        user_id=int(admin["sub"]),
        action="crawler_analyze",
        resource="crawler",
        detail={
            "analyzed_count": result.get("analyzed", 0),
            "known_pattern_hits": len(result.get("known_patterns", {})),
            "new_candidate_rules": candidate_rules,
        },
    )
    return result


@router.get("/stats")
async def case_stats(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """案例统计（各类型分布）"""
    return count_case_stats(db)
