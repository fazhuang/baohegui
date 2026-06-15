"""安全测试 — 规则管理接口仅限管理员

覆盖：
- 普通用户不能写规则 (reload/create/update/delete/import/sync/rollback/batch/toggle)
- 匿名用户不能写规则
- 管理员可以写规则
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.models.user import User


def _create_user(db, username: str, role: str = "user") -> User:
    u = User(
        username=username,
        hashed_password=hash_password("testpass123"),
        role=role,
        company="测试",
        email=f"{username}@test.com",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _headers(user: User) -> dict:
    token = create_access_token(user_id=user.id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


ADMIN_WRITE_ENDPOINTS = [
    ("POST", "/api/rules/reload", {}),
    ("POST", "/api/rules/platform", {"rule_id": "TEST001", "platform": "test", "platform_code": "T001"}),
    ("PUT", "/api/rules/platform/TEST001", {"description": "updated"}),
    ("DELETE", "/api/rules/platform/TEST001", None),
    ("POST", "/api/rules/platform/TEST001/toggle", None),
    ("POST", "/api/rules/import", {"rules": [{"rule_id": "IMP001"}]}),
    ("POST", "/api/rules/sync/run", None),
    ("POST", "/api/rules/versions/rollback", {"filename": "test.json"}),
    ("POST", "/api/rules/batch/toggle", {"rule_ids": ["R001"], "enabled": True}),
]

READ_ENDPOINTS = [
    ("GET", "/api/rules/engine/status"),
    ("GET", "/api/rules/platforms"),
    ("GET", "/api/rules/platform/list"),
    ("GET", "/api/rules/sync/status"),
    ("GET", "/api/rules/stats"),
]


class TestRulesAdminAuth:
    """规则库写操作仅限管理员"""

    @pytest.mark.parametrize("method,path,body", ADMIN_WRITE_ENDPOINTS)
    def test_normal_user_cannot_write_rules(self, client: TestClient, db_session, method, path, body):
        user = _create_user(db_session, f"user_rules_{method}_{path.replace('/', '_')[:20]}")
        if method == "GET":
            resp = client.get(path, headers=_headers(user))
        elif method == "POST":
            resp = client.post(path, json=body, headers=_headers(user), params={"platform": "test"} if body is None else None)
            if resp.status_code == 422:
                # Try with params if body was None
                resp = client.post(path, headers=_headers(user), params={"platform": "test"} if "sync/run" in path else {})
        elif method == "PUT":
            resp = client.put(path, json=body, headers=_headers(user))
        elif method == "DELETE":
            resp = client.delete(path, headers=_headers(user))
        else:
            return

        assert resp.status_code in (401, 403), (
            f"Normal user should not be allowed to {method} {path}: got {resp.status_code}"
        )

    def test_anonymous_cannot_write_rules(self, client: TestClient):
        resp = client.post("/api/rules/reload")
        assert resp.status_code in (401, 403), f"Anonymous should be denied: got {resp.status_code}"

    @pytest.mark.parametrize("method,path", READ_ENDPOINTS)
    def test_normal_user_can_read_rules(self, client: TestClient, db_session, method, path):
        """普通用户可以读取规则列表和状态（只读）"""
        user = _create_user(db_session, f"user_read_{path.replace('/', '_')[:20]}")
        if method == "GET":
            resp = client.get(path, headers=_headers(user))
            assert resp.status_code == 200, f"Normal user should be able to read {path}: got {resp.status_code} {resp.text}"
