"""Report API 测试"""

import json

import pytest
from fastapi import status


class TestReportEndpoints:
    """报告查询与导出测试"""

    def test_list_reports_empty(self, client, auth_headers):
        """空报告列表"""
        resp = client.get("/api/report/list/", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_report_not_found(self, client, auth_headers):
        """报告不存在"""
        resp = client.get("/api/report/99999", headers=auth_headers)
        assert resp.status_code == 404


class TestClauseGeneration:
    """合同条款生成测试"""

    def test_generate_clause_endpoint(self, client, auth_headers):
        """条款生成API测试"""
        resp = client.post(
            "/api/report/generate-clause",
            json={
                "original_text": "投标人须提供原厂授权函",
                "rule_description": "厂家授权锁：要求投标前取得厂家授权函",
                "suggestion": "可在中标后提供厂家授权或取消此要求",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "clauses" in data
        assert len(data["clauses"]) > 0
        assert "clause_title" in data["clauses"][0]
        assert "clause_text" in data["clauses"][0]
        assert data["model_used"] == "mock"

    def test_generate_clause_requires_auth(self, client):
        """条款生成需要认证"""
        resp = client.post(
            "/api/report/generate-clause",
            json={
                "original_text": "test",
                "suggestion": "test",
            },
        )
        assert resp.status_code in (401, 403)

    def test_generate_clause_validation(self, client, auth_headers):
        """缺少必填字段时返回422（Pydantic 校验）"""
        resp = client.post(
            "/api/report/generate-clause", json={}, headers=auth_headers
        )
        assert resp.status_code == 422

    def test_generate_clause_empty_original_text(self, client, auth_headers):
        """original_text为空时返回400"""
        resp = client.post(
            "/api/report/generate-clause",
            json={
                "original_text": "",
                "rule_description": "规则描述",
                "suggestion": "修复建议",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_generate_clause_empty_suggestion(self, client, auth_headers):
        """suggestion为空时返回400"""
        resp = client.post(
            "/api/report/generate-clause",
            json={
                "original_text": "问题文本",
                "rule_description": "规则描述",
                "suggestion": "",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_generate_clause_with_context(self, client, auth_headers):
        """带项目上下文的条款生成"""
        resp = client.post(
            "/api/report/generate-clause",
            json={
                "original_text": "投标人注册资本不低于1000万元",
                "rule_description": "隐形壁垒：以注册资金作为资格门槛",
                "suggestion": "删除注册资金要求或改为履约能力证明",
                "project_type": "公开招标",
                "budget": "500万元",
                "industry": "信息技术",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "clauses" in data
        # Mock mode returns a single clause
        assert len(data["clauses"]) >= 1


class TestFeedback:
    """审查反馈测试"""

    def test_feedback_missing_auth(self, client):
        """未认证提交反馈"""
        resp = client.post(
            "/api/report/feedback",
            json={
                "report_id": 1,
                "rule_id": "test_rule",
                "feedback_type": "confirm",
            },
        )
        assert resp.status_code in (401, 403)
