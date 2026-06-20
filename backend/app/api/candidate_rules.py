"""候选规则审核 API

Phase 2 — 候选规则管理：
- 候选规则列表（按审核状态过滤）
- 审核操作：通过/拒绝/标记重复
- 升级到正式规则资产
- 不得直接热加载生产规则
"""

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import audit_service
from app.core.security import get_current_user, require_admin
from app.db.database import get_db
from app.models.candidate_rule import CandidateRule
from app.services.rule_miner import promote_candidate_to_rule

router = APIRouter(prefix="/api/admin/candidate-rules", tags=["candidate-rules"])

MAX_LIMIT = 100
DEFAULT_LIMIT = 20


# ═══════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════


class BatchReviewRequest(BaseModel):
    """批量审核请求"""
    candidate_ids: list[int] = Field(..., min_length=1, max_length=200)
    action: str = Field(
        ...,
        pattern="^(approve|reject|mark_duplicate)$",
    )
    note: str = Field(default="", max_length=1000)
    promoted_rule_id: Optional[str] = Field(
        None,
        description="approve 时升级为正式规则的 rule_id"
    )


# ═══════════════════════════════════════════════════════
# 列表
# ═══════════════════════════════════════════════════════


@router.get("")
async def list_candidates(
    review_status: Optional[str] = Query(
        None,
        description="审核状态过滤: pending/approved/rejected/duplicate"
    ),
    source_type: Optional[str] = Query(None, description="来源: miner/manual/llm"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    risk_level: Optional[str] = Query(None, pattern="^(critical|high|medium|low)$"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """获取候选规则列表 — 仅管理员"""
    from sqlalchemy import or_

    q = db.query(CandidateRule)

    if review_status:
        q = q.filter(CandidateRule.review_status == review_status)
    else:
        # 默认显示待审核
        q = q.filter(CandidateRule.review_status == "pending")

    if source_type:
        q = q.filter(CandidateRule.source_type == source_type)

    if min_confidence > 0:
        q = q.filter(CandidateRule.confidence >= min_confidence)

    if risk_level:
        q = q.filter(CandidateRule.risk_level == risk_level)

    q = q.order_by(CandidateRule.confidence.desc(), CandidateRule.created_at.desc())

    total = q.count()
    candidates = q.offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "candidates": [c.to_dict() for c in candidates],
    }


@router.get("/stats")
async def candidate_stats(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """候选规则统计"""
    import sqlalchemy as sa

    stats = {}
    for st in ["pending", "approved", "rejected", "duplicate"]:
        stats[st] = db.query(CandidateRule).filter(
            CandidateRule.review_status == st
        ).count()

    # 风险分布
    risk_dist = {}
    for row in db.query(
        CandidateRule.risk_level,
        sa.func.count(CandidateRule.id),
    ).group_by(CandidateRule.risk_level).all():
        risk_dist[row[0]] = row[1]

    return {
        "by_status": stats,
        "pending_total": stats.get("pending", 0),
        "by_risk_level": risk_dist,
        "total": sum(stats.values()),
    }


# ═══════════════════════════════════════════════════════
# 详情
# ═══════════════════════════════════════════════════════


@router.get("/{candidate_id}")
async def candidate_detail(
    candidate_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """候选规则详情 — 含证据片段"""
    cand = db.query(CandidateRule).filter(CandidateRule.id == candidate_id).first()
    if not cand:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="候选规则不存在",
        )

    result = cand.to_dict()

    # 解析证据片段
    import json as _json
    if cand.evidence_snippets:
        try:
            result["evidence"] = _json.loads(cand.evidence_snippets)
        except (_json.JSONDecodeError, TypeError):
            result["evidence"] = {"raw": cand.evidence_snippets}

    # 关联的源案例
    if cand.source_case_id:
        from app.models.complaint_case import ComplaintCase
        source_case = db.query(ComplaintCase).filter(
            ComplaintCase.id == cand.source_case_id
        ).first()
        if source_case:
            result["source_case"] = {
                "id": source_case.id,
                "title": source_case.title,
                "decision_type": source_case.decision_type,
                "province": source_case.province,
                "review_status": source_case.review_status,
            }

    return result


# ═══════════════════════════════════════════════════════
# 审核操作
# ═══════════════════════════════════════════════════════


@router.post("/review")
async def review_candidates(
    body: BatchReviewRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """批量审核候选规则 — 仅管理员

    - approve: 标记为审核通过，可选升级为正式规则
    - reject: 标记为拒绝
    - mark_duplicate: 标记为重复
    """
    admin_id = int(admin["sub"])
    results = []
    errors = []

    for cid in body.candidate_ids:
        cand = db.query(CandidateRule).filter(CandidateRule.id == cid).first()
        if not cand:
            errors.append({"candidate_id": cid, "error": "候选规则不存在"})
            continue

        try:
            if body.action == "approve":
                if body.promoted_rule_id:
                    # 升级为正式规则
                    promo = promote_candidate_to_rule(
                        db, cid, admin_id, body.promoted_rule_id, note=body.note
                    )
                    if promo["success"]:
                        results.append({
                            "candidate_id": cid,
                            "action": "approved_and_promoted",
                            "candidate_rule_id": cand.candidate_id,
                            "promoted_to": body.promoted_rule_id,
                        })
                    else:
                        # 升级失败，仅审核通过
                        cand.approve(admin_id, note=body.note)
                        results.append({
                            "candidate_id": cid,
                            "action": "approved",
                            "candidate_rule_id": cand.candidate_id,
                            "promote_error": promo["error"],
                        })
                else:
                    cand.approve(admin_id, note=body.note)
                    results.append({
                        "candidate_id": cid,
                        "action": "approved",
                        "candidate_rule_id": cand.candidate_id,
                    })

            elif body.action == "reject":
                cand.reject(admin_id, note=body.note)
                results.append({
                    "candidate_id": cid,
                    "action": "rejected",
                    "candidate_rule_id": cand.candidate_id,
                })

            elif body.action == "mark_duplicate":
                cand.mark_duplicate(admin_id, note=body.note)
                results.append({
                    "candidate_id": cid,
                    "action": "marked_duplicate",
                    "candidate_rule_id": cand.candidate_id,
                })

        except Exception as e:
            errors.append({"candidate_id": cid, "error": str(e)})

    db.commit()

    audit_service.log(
        user_id=admin_id,
        action=f"candidate_rule_{body.action}",
        resource="candidate_rules",
        detail={
            "action": body.action,
            "note": body.note,
            "affected": len(results),
            "errors": len(errors),
        },
    )

    return {
        "action": body.action,
        "success_count": len(results),
        "error_count": len(errors),
        "results": results,
        "errors": errors,
    }
