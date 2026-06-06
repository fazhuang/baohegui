"""报告查询与导出 API"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.engine.fusion import ComplianceReport
from app.models.document import ComplianceReport as ReportModel
from app.services.feedback_service import feedback_service
from app.services.report_gen import report_generator

router = APIRouter(prefix="/api/report", tags=["report"])


@router.get("/{report_id}")
async def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """获取合规报告详情"""
    db_report = db.query(ReportModel).filter(ReportModel.id == report_id).first()
    if not db_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")

    return json.loads(db_report.report_data)


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


@router.get("/list/")
async def list_reports(
    limit: int = 20,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """列出最近的报告"""
    reports = db.query(ReportModel).order_by(ReportModel.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "file_id": r.file_id,
            "total_score": r.total_score,
            "violation_count": r.violation_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reports
    ]


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
    user: dict = Depends(get_current_user),
):
    """获取待审核的规则列表"""
    rules = feedback_service.get_rules_needing_review(db)
    return {"rules": rules}
