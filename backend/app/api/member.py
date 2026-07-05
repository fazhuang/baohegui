"""会员仪表盘 API — 工作台统计数据

所有决策字段从权威决策列（decision_action 等）读取。
旧报告缺少 PolicyDecision 时标记 legacy_unverifiable，不计入通过率。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.document import ComplianceReport, UploadedFile

router = APIRouter(prefix="/api/member", tags=["member"])


@router.get("/dashboard")
async def get_dashboard(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取当前用户的仪表盘统计数据。

    通过/失败判定来自权威决策列 decision_action。
    旧报告缺少决策列时标记 legacy_unverifiable，不计入通过率分母。
    """
    user_id = int(user.get("sub", 0))
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # ── 统计查询 ──────────────────────────────────────────
    total_reports = (
        db.query(func.count(ComplianceReport.id))
        .filter(ComplianceReport.checked_by == user_id)
        .scalar()
    ) or 0

    # 本月所有报告
    month_base = (
        db.query(ComplianceReport)
        .filter(
            ComplianceReport.checked_by == user_id,
            ComplianceReport.created_at >= month_start,
        )
    )

    reports_this_month = month_base.count()

    # 本月通过：decision_action == "pass" AND integrity_status == "verified"
    passed_count = (
        month_base.filter(
            ComplianceReport.decision_action == "pass",
            ComplianceReport.decision_integrity_status == "verified",
        ).count()
    )

    # 本月未通过（非 pass 但 verified）
    non_pass_verified = (
        month_base.filter(
            ComplianceReport.decision_action != "pass",
            ComplianceReport.decision_action.isnot(None),
            ComplianceReport.decision_integrity_status == "verified",
        ).count()
    )

    # 不可验证的历史报告
    legacy_count = (
        month_base.filter(
            ComplianceReport.decision_integrity_status == "legacy_unverifiable",
        ).count()
    ) + (
        month_base.filter(
            ComplianceReport.decision_integrity_status.is_(None),
        ).count()
    )

    # 通过率：分母只包含拥有有效已验证决策的报告
    verified_total = passed_count + non_pass_verified
    pass_rate = round(passed_count / verified_total * 100, 1) if verified_total > 0 else 0

    # 风险等级分布（本月）— 直接从决策列读取
    distribution = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    risk_counts = (
        db.query(
            ComplianceReport.decision_risk_level,
            func.count(ComplianceReport.id),
        )
        .filter(
            ComplianceReport.checked_by == user_id,
            ComplianceReport.created_at >= month_start,
            ComplianceReport.decision_risk_level.isnot(None),
        )
        .group_by(ComplianceReport.decision_risk_level)
        .all()
    )
    for level, cnt in risk_counts:
        if level in distribution:
            distribution[level] = cnt

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
            "final_action": _action_for_display(r.ComplianceReport),
            "risk_level": r.ComplianceReport.decision_risk_level or "unknown",
            "integrity_status": r.ComplianceReport.decision_integrity_status or "legacy_unverifiable",
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
            "failed_count": non_pass_verified,
            "legacy_unverifiable_count": legacy_count,
            "pass_rate": pass_rate,
            "risk_level_distribution": distribution,
            "recent": recent_reports,
            "monthly_trend": monthly_trend,
        },
    }


def _action_for_display(rep: ComplianceReport) -> str:
    if rep.decision_integrity_status == "legacy_unverifiable" or rep.decision_action is None:
        return "unknown"
    return rep.decision_action
