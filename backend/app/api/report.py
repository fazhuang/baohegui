"""报告查询与导出 API"""

import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.permissions import Permission, PermissionService
from app.core.security import get_current_user, get_current_user_id, assert_resource_access
from app.db.database import get_db
from app.engine.fusion import ComplianceReport
from app.models.document import ComplianceReport as ReportModel, UploadedFile
from app.services.excel_exporter import build_violation_rows, export_report_to_excel
from app.services.clause_generator import clause_generator
from app.services.feedback_service import feedback_service
from app.services.report_gen import report_generator

router = APIRouter(prefix="/api/report", tags=["report"])


def _load_report_violation_rows(db: Session, report_id: int, report_data: dict) -> list[dict]:
    """优先读取独立违规表，缺失时回退到 report_data 内的明细。"""
    try:
        from app.models.report_detail import ReportViolation as ReportViolationModel
    except ImportError:
        return build_violation_rows(report_data)

    rows = db.query(ReportViolationModel).filter(ReportViolationModel.report_id == report_id).all()
    if not rows:
        return build_violation_rows(report_data)

    violations: list[dict] = []
    for item in rows:
        violations.append(
            {
                "source": getattr(item, "source", ""),
                "rule_id": getattr(item, "rule_id", ""),
                "rule_type": getattr(item, "rule_type", ""),
                "risk_level": getattr(item, "risk_level", ""),
                "category": getattr(item, "category", ""),
                "title": getattr(item, "title", ""),
                "description": getattr(item, "description", ""),
                "evidence_text": getattr(item, "evidence_text", ""),
                "suggestion": getattr(item, "suggestion", ""),
                "law_ref": getattr(item, "law_ref", ""),
                "confidence": getattr(item, "confidence", ""),
            }
        )
    return violations


@router.get("/{report_id}")
async def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """获取合规报告详情（含规则溯源 + 决策完整性校验）"""
    db_report = db.query(ReportModel).filter(ReportModel.id == report_id).first()
    if not db_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    assert_resource_access(db, db_report, user, owner_attr="checked_by")
    report_dict = json.loads(db_report.report_data)

    # ── 决策完整性校验 ───────────────────────────────────────
    integrity_status = db_report.decision_integrity_status or "legacy_unverifiable"
    report_dict["_integrity"] = {
        "status": integrity_status,
        "decision_action": db_report.decision_action or "unknown",
        "decision_risk_level": db_report.decision_risk_level or "unknown",
        "decision_hash": db_report.decision_hash,
        "policy_schema_version": db_report.policy_schema_version,
    }

    # schema v2+: try verify_trace, fail closed if corrupted
    _di_raw = report_dict.get("_decision_input")
    _pd_raw = report_dict.get("_policy_decision")
    if _di_raw and _pd_raw and (db_report.policy_schema_version or "").startswith("2"):
        try:
            from app.core.policy_kernel import (
                DecisionInput, PolicyDecision, verify_trace,
            )
            di = DecisionInput.model_validate(_di_raw)
            pd = PolicyDecision.model_validate(_pd_raw)
            vr = verify_trace(di, pd)
            report_dict["_integrity"]["verify_result"] = vr
            if not vr["valid"]:
                report_dict["_integrity"]["status"] = "integrity_failed"
                report_dict["_integrity"]["warning"] = (
                    "决策完整性校验失败，本报告结论可能已被篡改。请重新执行合规审查。"
                )
        except Exception as e:
            report_dict["_integrity"]["verify_result"] = {"valid": False, "errors": [str(e)]}
            if integrity_status == "verified":
                report_dict["_integrity"]["status"] = "integrity_failed"
    elif not _di_raw:
        report_dict["_integrity"]["status"] = "legacy_unverifiable"
        report_dict["_integrity"]["warning"] = (
            "本报告为历史版本，缺少决策回放材料，无法执行完整性校验。"
            "合规结论仅供参考，建议重新执行审查。"
        )

    # v3: 注入规则溯源元数据
    from app.engine.rule_engine import rule_engine
    rule_provenance: dict[str, dict] = {}
    for rule in rule_engine.rules:
        rule_provenance[rule.id] = {
            "source_file": rule.source_file,
            "source_version": rule.source_version,
            "source_url": rule.source_url,
            "provenance": rule.provenance,
            "last_updated": rule.last_updated,
        }
    report_dict["_rule_provenance"] = rule_provenance

    return report_dict


@router.get("/{report_id}/pdf")
async def download_report_pdf(
    report_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """下载合规报告（PDF）"""
    db_report = db.query(ReportModel).filter(ReportModel.id == report_id).first()
    if not db_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    assert_resource_access(db, db_report, user, owner_attr="checked_by")
    report_data = json.loads(db_report.report_data)
    report = ComplianceReport(**report_data)

    pdf_path = report_generator.generate_pdf(report)
    with open(pdf_path, "rb") as f:
        pdf_content = f.read()

    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="baohegui_report_{report_id}.pdf"'},
    )


@router.get("/{report_id}/export")
async def export_report_excel(
    report_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """导出合规报告为 Excel 文件。"""
    db_report = db.query(ReportModel).filter(ReportModel.id == report_id).first()
    if not db_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    assert_resource_access(db, db_report, user, owner_attr="checked_by")

    report_data = json.loads(db_report.report_data) if db_report.report_data else {}
    violations = _load_report_violation_rows(db, report_id, report_data)
    output = export_report_to_excel(report_data, violations)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="baohegui_report_{report_id}.xlsx"'
        },
    )


@router.get("/list/")
async def list_reports(
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    score_min: float = 0,
    score_max: float = 100,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """列出报告，支持筛选、排序和分页。普通用户只能看自己的报告，管理员看全部。"""
    query = (
        db.query(ReportModel, UploadedFile.filename.label("file_name"))
        .outerjoin(UploadedFile, ReportModel.file_id == UploadedFile.id)
    )

    # 权限过滤：非管理员只能看到自己创建的检查报告
    if user.get("role") != "admin":
        user_id = get_current_user_id(user)
        query = query.filter(ReportModel.checked_by == user_id)

    if search.strip():
        query = query.filter(UploadedFile.filename.ilike(f"%{search.strip()}%"))

    if date_from:
        try:
            start_dt = datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_from 格式应为 YYYY-MM-DD") from exc
        query = query.filter(ReportModel.created_at >= start_dt)

    if date_to:
        try:
            end_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_to 格式应为 YYYY-MM-DD") from exc
        query = query.filter(ReportModel.created_at < end_dt)

    if score_min > 0:
        query = query.filter(ReportModel.total_score >= score_min)
    if score_max < 100:
        query = query.filter(ReportModel.total_score <= score_max)

    sort_key = sort_by.strip().lower()
    sort_field_map = {
        "id": ReportModel.id,
        "file_id": ReportModel.file_id,
        "file_name": UploadedFile.filename,
        "total_score": ReportModel.total_score,
        "violation_count": ReportModel.violation_count,
        "created_at": ReportModel.created_at,
    }
    sort_field = sort_field_map.get(sort_key, ReportModel.created_at)
    sort_direction = sort_order.strip().lower()
    order_clause = sort_field.asc() if sort_direction == "asc" else sort_field.desc()
    query = query.order_by(order_clause)

    total = query.order_by(None).count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [
        {
            "id": report.id,
            "file_id": report.file_id,
            "file_name": file_name or "",
            "total_score": report.total_score,
            "violation_count": report.violation_count,
            "created_at": report.created_at.isoformat() if report.created_at else None,
        }
        for report, file_name in rows
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    }


# ── 审查反馈 API ────────────────────────────────────────────


class FeedbackRequest(BaseModel):
    report_id: int
    rule_id: str
    feedback_type: str  # confirm / false_positive / missed
    comment: Optional[str] = None


@router.post("/feedback")
async def submit_feedback(
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """提交审查反馈"""
    # 检查报告是否存在
    db_report = db.query(ReportModel).filter(ReportModel.id == req.report_id).first()
    if not db_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    assert_resource_access(db, db_report, user, owner_attr="checked_by")

    try:
        result = feedback_service.submit_feedback(
            db=db,
            report_id=req.report_id,
            rule_id=req.rule_id,
            user_id=int(user["sub"]),
            feedback_type=req.feedback_type,
            comment=req.comment,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/feedback/rules-needing-review")
async def list_rules_needing_review(
    db: Session = Depends(get_db),
    user: dict = Depends(PermissionService.require_permission(Permission.RULES_READ)),
):
    """获取待审核的规则列表"""
    rules = feedback_service.get_rules_needing_review(db)
    return {"rules": rules}


# ── 智能条款生成 API ────────────────────────────────────────


class GenerateClauseRequest(BaseModel):
    original_text: str
    rule_description: str
    suggestion: str
    project_type: str = ""
    budget: str = ""
    industry: str = ""


@router.post("/generate-clause")
async def generate_clause(
    req: GenerateClauseRequest,
    user: dict = Depends(get_current_user),
):
    """生成合规替代条款"""
    if not req.original_text or not req.suggestion:
        raise HTTPException(status_code=400, detail="缺少必要参数 original_text 或 suggestion")

    result = await clause_generator.generate(
        original_text=req.original_text,
        rule_description=req.rule_description,
        suggestion=req.suggestion,
        project_type=req.project_type,
        budget=req.budget,
        industry=req.industry,
    )
    return result
