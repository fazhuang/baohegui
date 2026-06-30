"""P0 回归测试：普通用户不能修改规则

验证所有规则写端点（reload / sync / batch_toggle / rollback）被管理员权限保护。
"""

import pytest
from fastapi import status


class TestUserCannotWriteRules:
    """普通用户对规则写端点全部返回 403"""

    @pytest.fixture
    def user_headers(self, user_auth_headers):
        return user_auth_headers

    # ── 规则写入 ──────────────────────────────────────────

    def test_user_cannot_reload_rules(self, client, user_headers):
        """普通用户不能触发规则热加载"""
        resp = client.post("/api/rules/reload", headers=user_headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_user_cannot_sync_rules(self, client, user_headers):
        """普通用户不能触发规则同步"""
        resp = client.post("/api/rules/sync/run?platform=ccgp", headers=user_headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_user_cannot_batch_toggle_rules(self, client, user_headers):
        """普通用户不能批量启用/禁用规则"""
        resp = client.post("/api/rules/batch/toggle", json={"rule_ids": ["R001"]}, headers=user_headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_user_cannot_rollback_rules(self, client, user_headers):
        """普通用户不能回滚规则版本"""
        resp = client.post("/api/rules/versions/rollback", json={"filename": "v1.json"}, headers=user_headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    # ── 正向验证：管理员可以 ──────────────────────────────

    def test_admin_can_reload_rules(self, client, auth_headers):
        """管理员可以热加载规则（正向验证）"""
        resp = client.post("/api/rules/reload", headers=auth_headers)
        # 可能返回 200（成功）或 500（reload 内部因文件/规则原因失败）
        # 重点：不是 403
        assert resp.status_code != status.HTTP_403_FORBIDDEN

    # ── 未认证 ─────────────────────────────────────────────

    def test_anon_cannot_reload_rules(self, client):
        """未认证用户不能热加载规则"""
        resp = client.post("/api/rules/reload")
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_anon_cannot_sync_rules(self, client):
        """未认证用户不能同步规则"""
        resp = client.post("/api/rules/sync/run?platform=ccgp")
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_anon_cannot_toggle_rules(self, client):
        """未认证用户不能批量操作规则"""
        resp = client.post("/api/rules/batch/toggle", json={"rule_ids": ["R001"]})
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_anon_cannot_rollback_rules(self, client):
        """未认证用户不能回滚规则版本"""
        resp = client.post("/api/rules/versions/rollback", json={"filename": "v1.json"})
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


class TestUserCanReadRules:
    """普通用户可以读规则（只读端点是公开的）"""

    def test_user_can_get_rules_stats(self, client, user_auth_headers):
        """普通用户可以获取规则统计"""
        resp = client.get("/api/rules/stats", headers=user_auth_headers)
        assert resp.status_code == status.HTTP_200_OK

    def test_user_can_get_rules_versions(self, client, user_auth_headers):
        """普通用户可以获取规则版本列表"""
        resp = client.get("/api/rules/versions", headers=user_auth_headers)
        assert resp.status_code == status.HTTP_200_OK

    def test_user_can_get_rules_effectiveness(self, client, user_auth_headers):
        """普通用户可以获取规则效能统计"""
        resp = client.get("/api/rules/effectiveness", headers=user_auth_headers)
        assert resp.status_code == status.HTTP_200_OK
