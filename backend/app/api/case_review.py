"""案例审核管理 API

Phase 2 — 管理后台案例审核：
- 审核队列（按状态/来源/省份过滤）
- 原文 vs 脱敏内容对照
- 字段编辑
- 审核操作：通过/拒绝/隔离/下架
- 批量操作
- 审核理由 + 操作审计
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional

import sqlalchemy as sa
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.audit import audit_service
from app.core.security import get_current_user, require_admin
from app.db.database import get_db
from app.engine.case_state_machine import (
    CaseStatus,
    CaseStatusStateMachine,
    PublishStatus,
)
from app.models.complaint_case import ComplaintCase
from app.models.candidate_rule import CandidateRule
from app.services.dedup_service import dedup_service

router = APIRouter(prefix="/api/admin/cases", tags=["case-review"])

# ── 分页 ──
MAX_LIMIT = 100
DEFAULT_LIMIT = 20


# ═══════════════════════════════════════════════════════
# Request/Response models
# ═══════════════════════════════════════════════════════


class CaseUpdateRequest(BaseModel):
    """案例字段编辑请求"""
    title: Optional[str] = Field(None, max_length=255)
    project_name: Optional[str] = None
    project_number: Optional[str] = None
    case_no: Optional[str] = None
    city: Optional[str] = None
    complainant: Optional[str] = None
    respondent: Optional[str] = None
    decision_date: Optional[str] = None  # ISO date string
    decision_type: Optional[str] = None
    complaint_types: Optional[list[str]] = None
    legal_basis: Optional[list[str]] = None
    summary: Optional[str] = None
    sanitized_content: Optional[str] = None
    province: Optional[str] = None
    canonical_url: Optional[str] = None
    source_type: Optional[str] = None
    quality_score: Optional[float] = Field(None, ge=0.0, le=1.0)


class ReviewActionRequest(BaseModel):
    """审核操作请求"""
    action: str = Field(
        ...,
        pattern="^(approve|reject|quarantine|unpublish|republish|mark_duplicate|retry)$",
        description="approve/reject/quarantine/unpublish/republish/mark_duplicate/retry"
    )
    reason: str = Field(
        default="",
        max_length=1000,
        description="审核理由/备注"
    )
    case_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=200,
        description="案例 ID 列表（支持批量）"
    )
    mark_published: bool = Field(
        default=True,
        description="approve 时是否同时发布"
    )


class DedupCheckRequest(BaseModel):
    """去重检查请求"""
    case_id: int
    auto_mark: bool = True


# ═══════════════════════════════════════════════════════
# 审核队列
# ═══════════════════════════════════════════════════════


@router.get("/review-queue")
async def review_queue(
    review_status: Optional[str] = Query(
        None,
        description="审核状态过滤（逗号分隔多个）"
    ),
    source_type: Optional[str] = Query(None),
    province: Optional[str] = Query(None),
    decision_type: Optional[str] = Query(None),
    search: str = Query(default="", description="标题/项目名搜索"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("created_at", pattern="^(created_at|decision_date|quality_score)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """获取案例审核队列 — 仅管理员

    默认返回所有待处理状态的案例（非 published/archived）。
    支持多条件过滤、分页、排序。
    """
    q = db.query(ComplaintCase)

    # 状态过滤
    if review_status:
        statuses = [s.strip() for s in review_status.split(",") if s.strip()]
        if statuses:
            q = q.filter(ComplaintCase.review_status.in_(statuses))
    else:
        # 默认排除终态
        q = q.filter(
            ComplaintCase.review_status.in_([
                CaseStatus.FETCHED.value,
                CaseStatus.NORMALIZED.value,
                CaseStatus.EXTRACTED.value,
                CaseStatus.PENDING_REVIEW.value,
                CaseStatus.VERIFIED.value,
                CaseStatus.QUARANTINED.value,
                CaseStatus.PARSE_FAILED.value,
                CaseStatus.REJECTED.value,
                CaseStatus.DUPLICATE.value,
            ])
        )

    if source_type:
        q = q.filter(ComplaintCase.source_type == source_type)

    if province:
        q = q.filter(ComplaintCase.province == province)

    if decision_type:
        q = q.filter(ComplaintCase.decision_type == decision_type)

    if search:
        q = q.filter(
            or_(
                ComplaintCase.title.ilike(f"%{search}%"),
                ComplaintCase.project_name.ilike(f"%{search}%"),
            )
        )

    sort_col = getattr(ComplaintCase, sort_by)
    if sort_dir == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    total = q.count()
    cases = q.offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "cases": [_case_queue_item(c) for c in cases],
    }


@router.get("/review-queue/stats")
async def review_queue_stats(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """审核队列统计 — 各状态案例计数"""
    stats = {}
    for s in CaseStatus:
        count = db.query(ComplaintCase).filter(
            ComplaintCase.review_status == s.value
        ).count()
        stats[s.value] = count

    # 来源类型分布
    source_dist = {}
    for row in db.query(
        ComplaintCase.source_type,
        sa.func.count(ComplaintCase.id)
    ).group_by(ComplaintCase.source_type).all():
        source_dist[row[0] or "unknown"] = row[1]

    # 省份分布 (top 10)
    province_dist = {}
    for row in db.query(
        ComplaintCase.province,
        sa.func.count(ComplaintCase.id)
    ).group_by(ComplaintCase.province).order_by(
        sa.func.count(ComplaintCase.id).desc()
    ).limit(10).all():
        province_dist[row[0] or "未知"] = row[1]

    return {
        "by_status": stats,
        "pending_total": (
            stats.get("pending_review", 0) +
            stats.get("extracted", 0) +
            stats.get("normalized", 0) +
            stats.get("fetched", 0)
        ),
        "by_source_type": source_dist,
        "by_province": province_dist,
    }


# ═══════════════════════════════════════════════════════
# 案例详情（含原文 vs 脱敏对照）
# ═══════════════════════════════════════════════════════


@router.get("/{case_id}")
async def case_detail(
    case_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """获取案例详情 — 含原文与脱敏内容对照

    仅管理员可见 raw_content + sanitized_content + extraction_metadata。
    """
    case = db.query(ComplaintCase).filter(ComplaintCase.id == case_id).first()
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案例不存在",
        )

    result = case.to_dict()

    # 附加状态机信息
    result["allowed_transitions"] = CaseStatusStateMachine.get_allowed_transitions(
        case.review_status or "fetched"
    )

    # 去重检查
    dedup = dedup_service.find_duplicates(db, case, auto_mark=False)
    result["dedup_info"] = dedup

    # 关联候选规则
    candidate_rules = db.query(CandidateRule).filter(
        CandidateRule.source_case_id == case_id
    ).all()
    result["candidate_rules"] = [
        {
            "id": r.id,
            "candidate_id": r.candidate_id,
            "description": r.description,
            "review_status": r.review_status,
            "confidence": r.confidence,
        }
        for r in candidate_rules
    ]

    return result


# ═══════════════════════════════════════════════════════
# 字段编辑
# ═══════════════════════════════════════════════════════


@router.put("/{case_id}")
async def update_case(
    case_id: int,
    body: CaseUpdateRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """编辑案例字段 — 仅管理员

    可编辑字段：title, project_name, project_number, case_no, city,
    complainant, respondent, decision_date, decision_type,
    complaint_types, legal_basis, summary, sanitized_content,
    province, canonical_url, source_type, quality_score
    """
    case = db.query(ComplaintCase).filter(ComplaintCase.id == case_id).first()
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案例不存在",
        )

    changes = {}

    # 文本字段
    str_fields = [
        "title", "project_name", "project_number", "case_no", "city",
        "complainant", "respondent", "summary", "sanitized_content",
        "province", "canonical_url", "source_type",
    ]
    for field in str_fields:
        val = getattr(body, field, None)
        if val is not None:
            setattr(case, field, val)
            changes[field] = val

    # 枚举字段
    for field in ["decision_type"]:
        val = getattr(body, field, None)
        if val is not None:
            setattr(case, field, val)
            changes[field] = val

    # Date 字段
    if body.decision_date is not None:
        try:
            case.decision_date = date.fromisoformat(body.decision_date) if body.decision_date else None
            changes["decision_date"] = body.decision_date
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"无效日期格式: {body.decision_date}，需要 YYYY-MM-DD",
            )

    # JSON 数组字段
    if body.complaint_types is not None:
        case.set_complaint_types(body.complaint_types)
        changes["complaint_types"] = body.complaint_types

    if body.legal_basis is not None:
        case.set_legal_basis(body.legal_basis)
        changes["legal_basis"] = body.legal_basis

    # 数值字段
    if body.quality_score is not None:
        case.quality_score = body.quality_score
        changes["quality_score"] = body.quality_score

    db.commit()

    audit_service.log(
        user_id=int(admin["sub"]),
        action="case_update",
        resource="complaint_case",
        resource_id=str(case_id),
        detail=changes,
    )

    return {
        "id": case.id,
        "updated_fields": list(changes.keys()),
    }


# ═══════════════════════════════════════════════════════
# 审核操作（单个/批量）
# ═══════════════════════════════════════════════════════


@router.post("/review")
async def review_cases(
    body: ReviewActionRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """审核案例 — 支持批量和多种操作

    Phase 2: 状态变更与 KG 投影在同一事务内，投影失败时回滚案例状态。
    批量操作使用 per-case savepoint，单条失败不影响其他成功项。

    操作类型：
    - approve:   pending_review → verified → (可选 published)
    - reject:    pending_review → rejected
    - quarantine: any → quarantined
    - unpublish: published → unpublished
    - mark_duplicate: any → duplicate
    - retry:      rejected/parse_failed/duplicate → fetched
    """
    sm = CaseStatusStateMachine()
    admin_id = int(admin["sub"])

    results = []
    errors = []

    for case_id in body.case_ids:
        # Per-case savepoint: 单条失败不破坏其他成功项
        try:
            db.begin_nested()
        except Exception:
            pass  # SQLite may not support savepoints; fall through

        try:
            case = db.query(ComplaintCase).filter(
                ComplaintCase.id == case_id
            ).first()

            if not case:
                errors.append({"case_id": case_id, "error": "案例不存在"})
                db.rollback()
                continue

            current_status = case.review_status or "fetched"
            note = body.reason

            if body.action == "approve":
                # pending_review → verified → published
                # 安全检查：脱敏内容为空时禁止发布
                if body.mark_published and not (case.sanitized_content or "").strip():
                    errors.append({
                        "case_id": case_id,
                        "error": "脱敏内容为空，无法发布。请先编辑 sanitized_content 后再审核通过。"
                    })
                    db.rollback()
                    continue
                target = CaseStatus.VERIFIED.value
                ok, msg = sm.transition(case, target, user_id=admin_id, note=note)
                if not ok:
                    errors.append({"case_id": case_id, "error": msg})
                    db.rollback()
                    continue
                if body.mark_published:
                    sm.transition(case, CaseStatus.PUBLISHED.value, user_id=admin_id)

            elif body.action == "reject":
                target = CaseStatus.REJECTED.value
                ok, msg = sm.transition(case, target, user_id=admin_id, note=note)
                if not ok:
                    errors.append({"case_id": case_id, "error": msg})
                    db.rollback()
                    continue

            elif body.action == "quarantine":
                target = CaseStatus.QUARANTINED.value
                ok, msg = sm.transition(case, target, user_id=admin_id, note=note)
                if not ok:
                    errors.append({"case_id": case_id, "error": msg})
                    db.rollback()
                    continue

            elif body.action == "unpublish":
                target = CaseStatus.UNPUBLISHED.value
                ok, msg = sm.transition(case, target, user_id=admin_id, note=note)
                if not ok:
                    errors.append({"case_id": case_id, "error": msg})
                    db.rollback()
                    continue

            elif body.action == "republish":
                # unpublished → published (re-publish a previously unpublished case)
                target = CaseStatus.PUBLISHED.value
                ok, msg = sm.transition(case, target, user_id=admin_id, note=note)
                if not ok:
                    errors.append({"case_id": case_id, "error": msg})
                    db.rollback()
                    continue

            elif body.action == "mark_duplicate":
                target = CaseStatus.DUPLICATE.value
                ok, msg = sm.transition(case, target, user_id=admin_id, note=note)
                if not ok:
                    errors.append({"case_id": case_id, "error": msg})
                    db.rollback()
                    continue

            elif body.action == "retry":
                target = CaseStatus.FETCHED.value
                ok, msg = sm.transition(case, target, user_id=admin_id, note=note)
                if not ok:
                    errors.append({"case_id": case_id, "error": msg})
                    db.rollback()
                    continue

            # ── KG 投影（与状态变更原子操作） ──
            kg_error = None
            if case.review_status == CaseStatus.PUBLISHED.value:
                from app.services.kg_projection import kg_projection
                kg_result = kg_projection.project_case(db, case)
                if not kg_result["success"]:
                    kg_error = kg_result.get("error", "KG projection failed")
                    logger.error(f"案例 {case_id} KG 投影失败: {kg_error}")
                    errors.append({"case_id": case_id, "error": f"KG 投影失败: {kg_error}"})
                    db.rollback()
                    continue
            elif case.review_status == CaseStatus.UNPUBLISHED.value:
                from app.services.kg_projection import kg_projection
                kg_result = kg_projection.unproject_case(db, case)
                if not kg_result["success"]:
                    kg_error = kg_result.get("error", "KG unproject failed")
                    logger.error(f"案例 {case_id} KG 下架失败: {kg_error}")
                    errors.append({"case_id": case_id, "error": f"KG 下架失败: {kg_error}"})
                    db.rollback()
                    continue

            results.append({
                "case_id": case_id,
                "from_status": current_status,
                "to_status": case.review_status,
                "title": case.title,
            })

        except Exception as e:
            errors.append({"case_id": case_id, "error": str(e)})
            db.rollback()
            continue

    db.commit()

    # 审计日志
    audit_service.log(
        user_id=admin_id,
        action=f"case_review_{body.action}",
        resource="complaint_case",
        detail={
            "action": body.action,
            "reason": body.reason,
            "affected": len(results),
            "errors": len(errors),
            "case_ids": [r["case_id"] for r in results],
        },
    )

    return {
        "action": body.action,
        "success_count": len(results),
        "error_count": len(errors),
        "results": results,
        "errors": errors,
    }


# ═══════════════════════════════════════════════════════
# 去重检查
# ═══════════════════════════════════════════════════════


@router.post("/dedup-check")
async def dedup_check(
    body: DedupCheckRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """对单个案例执行去重检查"""
    case = db.query(ComplaintCase).filter(
        ComplaintCase.id == body.case_id
    ).first()
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案例不存在",
        )

    result = dedup_service.find_duplicates(db, case, auto_mark=body.auto_mark)
    return result


@router.post("/bulk-dedup")
async def bulk_dedup(
    case_ids: Optional[list[int]] = Body(None, embed=True),
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """批量去重检查"""
    result = dedup_service.bulk_dedup_check(db, case_ids=case_ids)
    audit_service.log(
        user_id=int(admin["sub"]),
        action="case_bulk_dedup",
        resource="complaint_case",
        detail=result,
    )
    return result


# ═══════════════════════════════════════════════════════
# 公共接口（普通用户）
# ═══════════════════════════════════════════════════════


@router.get("/public/list")
async def public_case_list(
    province: Optional[str] = Query(None),
    decision_type: Optional[str] = Query(None),
    search: str = Query(default=""),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """公开案例列表 — 仅 published 案例"""
    from sqlalchemy import or_

    q = db.query(ComplaintCase).filter(
        ComplaintCase.review_status == CaseStatus.PUBLISHED.value,
        ComplaintCase.publish_status == PublishStatus.PUBLISHED.value,
    )

    if province:
        q = q.filter(ComplaintCase.province == province)

    if decision_type:
        q = q.filter(ComplaintCase.decision_type == decision_type)

    if search:
        q = q.filter(
            or_(
                ComplaintCase.title.ilike(f"%{search}%"),
                ComplaintCase.sanitized_content.ilike(f"%{search}%"),
                ComplaintCase.summary.ilike(f"%{search}%"),
            )
        )

    q = q.order_by(ComplaintCase.published_at.desc())

    total = q.count()
    cases = q.offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "cases": [c.to_public_dict() for c in cases],
    }


@router.get("/public/{case_id}")
async def public_case_detail(
    case_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """公开案例详情 — 仅 published"""
    case = db.query(ComplaintCase).filter(
        ComplaintCase.id == case_id,
        ComplaintCase.review_status == CaseStatus.PUBLISHED.value,
        ComplaintCase.publish_status == PublishStatus.PUBLISHED.value,
    ).first()

    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案例不存在或未发布",
        )

    return case.to_public_dict()


# ═══════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════


def _case_queue_item(case: ComplaintCase) -> dict:
    """审核队列列表项"""
    return {
        "id": case.id,
        "title": case.title,
        "province": case.province,
        "source_url": case.source_url,
        "source_type": case.source_type,
        "project_name": case.project_name,
        "project_number": case.project_number,
        "case_no": case.case_no,
        "city": case.city,
        "decision_date": case.decision_date.isoformat() if case.decision_date else None,
        "decision_type": case.decision_type,
        "review_status": case.review_status or "fetched",
        "publish_status": case.publish_status or "draft",
        "quality_score": case.quality_score or 0.0,
        "content_hash": case.content_hash,
        "has_raw": bool(case.raw_content),
        "has_sanitized": bool(case.sanitized_content),
        "is_analyzed": case.is_analyzed,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "allowed_transitions": CaseStatusStateMachine.get_allowed_transitions(
            case.review_status or "fetched"
        ),
    }
