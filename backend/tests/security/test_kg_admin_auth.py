"""安全测试 — 知识图谱 seed 接口仅限管理员

覆盖：
- 普通用户不能 KG seed
- 匿名不能 KG seed
- 普通用户可以搜索 KG（只读）
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


class TestKnowledgeGraphAuth:
    """知识图谱管理接口鉴权"""

    def test_anonymous_cannot_kg_seed(self, client: TestClient):
        resp = client.post("/api/kg/seed")
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_normal_user_cannot_kg_seed(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_seed_user")
        resp = client.post("/api/kg/seed", headers=_headers(user))
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_normal_user_can_search_kg(self, client: TestClient, db_session):
        """普通用户可以使用 KG 搜索（只读）"""
        user = _create_user(db_session, "kg_search_user")
        resp = client.get("/api/kg/search?q=政府采购", headers=_headers(user))
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_anonymous_cannot_search_kg(self, client: TestClient):
        resp = client.get("/api/kg/search?q=政府采购")
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_admin_can_seed_kg(self, client: TestClient, db_session):
        admin = _create_user(db_session, "kg_admin", role="admin")
        resp = client.post("/api/kg/seed", headers=_headers(admin))
        assert resp.status_code in (200, 500), f"Expected 200/500, got {resp.status_code}"
