"""规则管理后台API测试"""
import pytest


class TestRulesAdminAPI:
    """规则管理后台接口测试"""

    def test_rules_stats(self, client, auth_headers):
        """获取规则统计"""
        resp = client.get("/api/rules/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_rules" in data
        assert data["total_rules"] > 0

    def test_rules_versions(self, client, auth_headers):
        """获取版本列表"""
        resp = client.get("/api/rules/versions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "versions" in data

    def test_rules_effectiveness(self, client, auth_headers):
        """获取规则效能统计"""
        resp = client.get("/api/rules/effectiveness", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "rules" in data
        assert "total_reports" in data

    def test_batch_toggle_requires_auth(self, client):
        """批量操作需要认证"""
        resp = client.post("/api/rules/batch/toggle", json={"rule_ids": ["R001"]})
        assert resp.status_code in (401, 403)

    def test_batch_toggle_requires_rule_ids(self, client, auth_headers):
        """缺少 rule_ids 参数时返回错误"""
        resp = client.post("/api/rules/batch/toggle", json={}, headers=auth_headers)
        assert resp.status_code == 400

    def test_rollback_requires_filename(self, client, auth_headers):
        """回滚缺少参数时返回错误"""
        resp = client.post("/api/rules/versions/rollback", json={}, headers=auth_headers)
        assert resp.status_code == 400

    def test_list_platforms(self, client, auth_headers):
        """获取多平台列表"""
        resp = client.get("/api/rules/platforms", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "platforms" in data
