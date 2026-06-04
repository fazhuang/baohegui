"""会员仪表盘 API — 工作台统计数据"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.document import ComplianceReport, UploadedFile

router = APIRouter(prefix="/api/member", tags=["member"])

# 风险等级中文映射
RISK_CN: dict[str, str] = {
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
    "pass": "通过",
    "critical": "严重",
}


def _compute_risk_level(score: float) -> str:
    """根据总分计算风险等级"""
    if score >= 85:
        return "pass"
    elif score >= 60:
        return "medium"
    elif score >= 40:
        return "high"
    return "critical"


@router.get("/dashboard")
async def get_dashboard(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取当前用户的仪表盘统计数据"""
    user_id = int(user.get("sub", 0))
    now = datetime.now(timezone.utc)

    # 本月起止时间
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # ── 统计查询 ──────────────────────────────────────────
    # 累计审查次数
    total_reports = (
        db.query(func.count(ComplianceReport.id))
        .filter(ComplianceReport.checked_by == user_id)
        .scalar()
    ) or 0

    # 本月审查次数
    reports_this_month = (
        db.query(func.count(ComplianceReport.id))
        .filter(
            ComplianceReport.checked_by == user_id,
            ComplianceReport.created_at >= month_start,
        )
        .scalar()
    ) or 0

    # 本月通过的审查数（总分 >= 85 视为通过）
    passed_count = (
        db.query(func.count(ComplianceReport.id))
        .filter(
            ComplianceReport.checked_by == user_id,
            ComplianceReport.created_at >= month_start,
            ComplianceReport.total_score >= 85,
        )
        .scalar()
    ) or 0

    # 本月未通过的审查数
    failed_count = reports_this_month - passed_count

    # 通过率
    pass_rate = round(passed_count / reports_this_month * 100, 1) if reports_this_month > 0 else 0

    # 风险等级分布（本月）
    distribution = {level: 0 for level in ["critical", "high", "medium", "low"]}
    recent_scores = (
        db.query(ComplianceReport.total_score)
        .filter(
            ComplianceReport.checked_by == user_id,
            ComplianceReport.created_at >= month_start,
        )
        .all()
    )
    for (score,) in recent_scores:
        level = _compute_risk_level(score)
        if level in distribution:
            distribution[level] += 1

    # 最近审查记录（最近 5 条）
    recent_raw = (
        db.query(ComplianceReport, UploadedFile.filename)
        .join(UploadedFile, ComplianceReport.file_id == UploadedFile.id)
        .filter(ComplianceReport.checked_by == user_id)
        .order_by(ComplianceReport.created_at.desc())
        .limit(5)
        .all()
    )
    recent_reports = [
        {
            "id": r.ComplianceReport.id,
            "source_file": filename or "",
            "status": "completed",
            "risk_level": _compute_risk_level(r.ComplianceReport.total_score),
            "risk_level_cn": RISK_CN.get(_compute_risk_level(r.ComplianceReport.total_score), ""),
            "created_at": r.ComplianceReport.created_at.isoformat() if r.ComplianceReport.created_at else "",
        }
        for r, filename in recent_raw
    ]

    # 月度趋势（最近 6 个月）
    monthly_trend: list[dict] = []
    for i in range(5, -1, -1):
        m = (month_start.month - i - 1) % 12 + 1
        y = month_start.year + (month_start.month - i - 1) // 12
        count = (
            db.query(func.count(ComplianceReport.id))
            .filter(
                ComplianceReport.checked_by == user_id,
                extract("year", ComplianceReport.created_at) == y,
                extract("month", ComplianceReport.created_at) == m,
            )
            .scalar()
        ) or 0
        monthly_trend.append({
            "month": f"{y}-{m:02d}",
            "count": count,
        })

    return {
        "compliance": {
            "total_reports": total_reports,
            "reports_this_month": reports_this_month,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "pass_rate": pass_rate,
            "risk_level_distribution": distribution,
            "recent": recent_reports,
            "monthly_trend": monthly_trend,
        },
    }
