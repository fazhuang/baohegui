"""零Token路由审查测试"""
import pytest
from app.engine.routing import ComplianceRouter
from app.engine.shared_types import TrafficLight, RoutingResult


class TestComplianceRouter:
    """零Token路由审查单元测试"""

    def test_green_light_small_budget_open_bidding(self):
        """小额公开招标 → 绿灯，跳过LLM"""
        router = ComplianceRouter()
        result = router.route(
            budget=500_000,
            procurement_method="公开招标",
            project_type="货物类",
        )
        assert result.traffic_light == TrafficLight.GREEN
        assert result.skip_llm is True
        assert len(result.llm_task_list) == 0

    def test_red_light_large_budget_single_source(self):
        """大额单一来源 → 红灯，五层全开"""
        router = ComplianceRouter()
        result = router.route(
            budget=10_000_000,
            procurement_method="单一来源",
            project_type="服务类",
        )
        assert result.traffic_light == TrafficLight.RED
        assert result.skip_llm is False
        assert len(result.llm_task_list) > 0

    def test_yellow_light_medium_budget_invitation(self):
        """中等预算邀请招标 → 黄灯，LLM关键维度"""
        router = ComplianceRouter()
        result = router.route(
            budget=3_000_000,
            procurement_method="邀请招标",
            project_type="工程类",
        )
        assert result.traffic_light == TrafficLight.YELLOW
        assert result.skip_llm is False

    def test_routing_unknown_method_defaults_to_yellow(self):
        """未知采购方式 → 默认黄灯，保守处理"""
        router = ComplianceRouter()
        result = router.route(
            budget=2_000_000,
            procurement_method="未知采购方式",
            project_type="货物类",
        )
        assert result.traffic_light in (TrafficLight.YELLOW, TrafficLight.RED)

    def test_routing_result_is_serializable(self):
        """路由结果可序列化"""
        router = ComplianceRouter()
        result = router.route(budget=500_000, procurement_method="公开招标", project_type="货物类")
        d = result.model_dump()
        assert d["traffic_light"] == "green"
        assert "reasoning" in d
