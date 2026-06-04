"""使用统计 API — 管理员看板数据"""

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.engine.rule_engine import rule_engine
from app.services.usage_tracker import usage_tracker

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/dashboard")
async def get_dashboard_stats(user: dict = Depends(get_current_user)):
    """管理员看板 — 系统使用统计"""

    # 规则引擎统计
    rules = rule_engine.rules
    by_type: dict[str, int] = {}
    for r in rules:
        by_type[r.type] = by_type.get(r.type, 0) + 1
    total_rules = len(rules)

    # LLM 调用统计
    llm_stats = usage_tracker.get_stats()
    recent_calls = usage_tracker.get_recent(5)

    # 按类型统计违规分布（基于规则权重）
    risk_distribution = {
        "high": sum(1 for r in rules if getattr(r, "severity", "medium") == "high"
                    or (r.type == "chapter_required" and r.weight >= 20)),
        "medium": sum(1 for r in rules if not (
            getattr(r, "severity", "medium") == "high"
            or (r.type == "chapter_required" and r.weight >= 20)
            or getattr(r, "severity", "medium") == "low")
            and getattr(r, "severity", "medium") != "low"),
        "low": sum(1 for r in rules if getattr(r, "severity", "medium") == "low"),
    }

    return {
        "rules": {
            "total": total_rules,
            "by_type": by_type,
            "chapter_required": by_type.get("chapter_required", 0),
            "keyword_required": by_type.get("keyword_required", 0),
            "forbidden": by_type.get("forbidden", 0),
            "format_required": by_type.get("format_required", 0),
        },
        "llm": {
            "total_calls": llm_stats.total_calls,
            "total_tokens": llm_stats.total_tokens,
            "total_cost": llm_stats.total_cost_yuan,
            "success_rate": llm_stats.success_rate,
            "avg_tokens_per_call": llm_stats.avg_tokens_per_call,
            "calls_by_model": llm_stats.calls_by_model,
            "recent_calls": [
                {
                    "model": r.model,
                    "tokens": r.total_tokens,
                    "duration": round(r.duration_seconds, 2),
                    "success": r.success,
                    "timestamp": r.timestamp,
                }
                for r in recent_calls
            ],
        },
        "risk_distribution": risk_distribution,
        "industries": rule_engine.list_industries(),
    }
