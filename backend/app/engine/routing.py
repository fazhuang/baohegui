"""零Token路由审查引擎

第0层审查：在调用任何规则引擎或LLM之前，仅通过结构化字段
（预算金额、采购方式、项目类型）快速判断审查深度。

输出交通灯等级 + LLM任务列表，零LLM Token消耗。
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings
from app.engine.shared_types import RoutingResult, TrafficLight

logger = logging.getLogger(__name__)


class ComplianceRouter:
    """零Token路由审查器"""

    def route(
        self,
        budget: Optional[float] = None,
        procurement_method: str = "",
        project_type: str = "",
    ) -> RoutingResult:
        """
        根据预算金额和采购方式确定审查深度。

        Args:
            budget: 项目预算金额（元）
            procurement_method: 采购方式（公开招标/邀请招标/竞争性谈判/竞争性磋商/询价/单一来源）
            project_type: 项目类型（货物类/服务类/工程类）

        Returns:
            RoutingResult with traffic_light, skip_llm flag, llm_task_list
        """
        reasons: list[str] = []

        # ── 采购方式风险分级 ──────────────────────────────────
        is_red_method = procurement_method in settings.routing_red_methods
        is_yellow_method = procurement_method in settings.routing_yellow_methods

        if is_red_method:
            reasons.append(f"采购方式: {procurement_method}（高风险）")
        elif is_yellow_method:
            reasons.append(f"采购方式: {procurement_method}（中风险）")

        # ── 预算金额风险分级 ──────────────────────────────────
        budget_risk = "low"
        if budget is not None:
            if budget > settings.routing_yellow_budget_max:
                budget_risk = "high"
                reasons.append(f"预算金额: {budget:,.0f}元（超500万，高风险）")
            elif budget > settings.routing_green_budget_max:
                budget_risk = "medium"
                reasons.append(f"预算金额: {budget:,.0f}元（100-500万，中风险）")
            else:
                reasons.append(f"预算金额: {budget:,.0f}元（≤100万，低风险）")

        # ── 综合判定交通灯 ────────────────────────────────────
        if is_red_method or budget_risk == "high":
            traffic_light = TrafficLight.RED
            skip_llm = False
            llm_task_list = [
                "AI-BRAND", "AI-AUTH", "AI-LAB", "AI-PATENT",
                "AI-COMBINE", "AI-STD", "AI-SCORE-VAGUE",
                "AI-PRICE-WEIGHT", "AI-SCORE-SUBJ", "AI-QUAL-LEVEL",
                "AI-QUAL-RESTRICT", "AI-QUAL-CERT", "AI-REJECT",
                "AI-COMPLAINT", "AI-SME", "AI-CREDIT", "AI-GREEN",
            ]
        elif is_yellow_method or budget_risk == "medium":
            traffic_light = TrafficLight.YELLOW
            skip_llm = False
            llm_task_list = [
                "AI-BRAND", "AI-AUTH", "AI-COMBINE",
                "AI-QUAL-RESTRICT", "AI-REJECT", "AI-COMPLAINT",
            ]
        else:
            traffic_light = TrafficLight.GREEN
            skip_llm = True
            llm_task_list = []

        reasoning = "；".join(reasons) if reasons else "预算和采购方式均为低风险"

        logger.info(
            "路由判定: %s | skip_llm=%s | tasks=%d | %s",
            traffic_light.value,
            skip_llm,
            len(llm_task_list),
            reasoning,
        )

        return RoutingResult(
            traffic_light=traffic_light,
            risk_summary=f"交通灯: {traffic_light.value}",
            llm_task_list=llm_task_list,
            skip_llm=skip_llm,
            reasoning=reasoning,
        )


# ── 全局单例 ──────────────────────────────────────────────────
compliance_router = ComplianceRouter()
