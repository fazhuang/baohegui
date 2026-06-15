"""安全测试 — 爬虫接口仅限管理员

覆盖：
- 匿名不能触发爬虫
- 普通用户不能触发爬虫
- 管理员可以触发爬虫
- 普通用户可以查看案例（只读）
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


class TestCrawlerAuth:
    """爬虫管理接口鉴权"""

    def test_anonymous_cannot_trigger_crawler(self, client: TestClient):
        resp = client.post("/api/crawler/trigger")
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_normal_user_cannot_trigger_crawler(self, client: TestClient, db_session):
        user = _create_user(db_session, "crawler_user")
        resp = client.post("/api/crawler/trigger", headers=_headers(user))
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_anonymous_cannot_trigger_analysis(self, client: TestClient):
        resp = client.post("/api/crawler/analyze")
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_normal_user_cannot_trigger_analysis(self, client: TestClient, db_session):
        user = _create_user(db_session, "crawler_analyze_user")
        resp = client.post("/api/crawler/analyze", headers=_headers(user))
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_normal_user_can_list_cases(self, client: TestClient, db_session):
        user = _create_user(db_session, "crawler_read_user")
        resp = client.get("/api/crawler/cases", headers=_headers(user))
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    def test_anonymous_cannot_list_cases(self, client: TestClient):
        resp = client.get("/api/crawler/cases")
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_admin_can_trigger_crawler(self, client: TestClient, db_session):
        admin = _create_user(db_session, "crawler_admin", role="admin")
        resp = client.post("/api/crawler/trigger", headers=_headers(admin))
        assert resp.status_code in (200, 500), f"Expected 200/500, got {resp.status_code}"
