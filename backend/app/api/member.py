"""会员仪表盘 API — 工作台统计数据

所有决策字段从 policy_decision / _policy_decision 读取，不再从 total_score 推导。
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

    通过/失败判定来自持久化的 policy_decision，不再使用 total_score >= 85。
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

    reports_this_month = (
        db.query(func.count(ComplianceReport.id))
        .filter(
            ComplianceReport.checked_by == user_id,
            ComplianceReport.created_at >= month_start,
        )
        .scalar()
    ) or 0

    # 本月通过/未通过：从 report_data._policy_decision 或 _merge_result.final_passed 判定
    # 由于 policy_decision 暂未作为独立列存储，先统计 report_data JSON 中已持久化的值。
    # ponytail: JSON 字段内提取无法在 SQL 层高效完成，保留应用层统计作为兼容策略。
    # 当 decision_action 列落地后替换为直接 SQL 查询。
    all_month_reports = (
        db.query(ComplianceReport.id, ComplianceReport.report_data)
        .filter(
            ComplianceReport.checked_by == user_id,
            ComplianceReport.created_at >= month_start,
        )
        .all()
    )

    import json as _json
    passed_count = 0
    for rid, raw in all_month_reports:
        try:
            data = _json.loads(raw) if isinstance(raw, str) else (raw or {})
        except _json.JSONDecodeError:
            data = {}
        # 优先从 _policy_decision 读取，回退到 _merge_result（兼容旧数据）
        pd = data.get("_policy_decision", {})
        if pd and "final_action" in pd:
            if pd.get("final_action") == "pass":
                passed_count += 1
        else:
            mr = data.get("_merge_result", {})
            if mr and mr.get("final_passed") is not None:
                if mr.get("final_passed"):
                    passed_count += 1
            else:
                # 最终回退：旧 total_score >= 85
                score = data.get("total_score", 0)
                if score >= 85:
                    passed_count += 1

    failed_count = reports_this_month - passed_count
    pass_rate = round(passed_count / reports_this_month * 100, 1) if reports_this_month > 0 else 0

    # 风险等级分布（本月）— 从 policy_decision 读取
    distribution = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for rid, raw in all_month_reports:
        try:
            data = _json.loads(raw) if isinstance(raw, str) else (raw or {})
        except _json.JSONDecodeError:
            continue
        pd = data.get("_policy_decision", {})
        if pd and "final_risk_level" in pd:
            level = pd["final_risk_level"]
        else:
            mr = data.get("_merge_result", {})
            level = mr.get("risk_level", "low") if mr else "low"
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

    def _extract_action_from_report(rep: ComplianceReport) -> str:
        try:
            raw = rep.report_data
            data = _json.loads(raw) if isinstance(raw, str) else (raw or {})
        except _json.JSONDecodeError:
            return "unknown"
        pd = data.get("_policy_decision", {})
        if pd and "final_action" in pd:
            return pd["final_action"]
        mr = data.get("_merge_result", {})
        if mr and mr.get("final_passed") is not None:
            return "pass" if mr["final_passed"] else "failed"
        score = data.get("total_score", 0)
        return "pass" if score >= 85 else "failed"

    def _extract_risk_from_report(rep: ComplianceReport) -> str:
        try:
            raw = rep.report_data
            data = _json.loads(raw) if isinstance(raw, str) else (raw or {})
        except _json.JSONDecodeError:
            return "low"
        pd = data.get("_policy_decision", {})
        if pd and "final_risk_level" in pd:
            return pd["final_risk_level"]
        mr = data.get("_merge_result", {})
        return mr.get("risk_level", "low") if mr else "low"

    recent_reports = [
        {
            "id": r.ComplianceReport.id,
            "source_file": filename or "",
            "status": "completed",
            "final_action": _extract_action_from_report(r.ComplianceReport),
            "risk_level": _extract_risk_from_report(r.ComplianceReport),
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
