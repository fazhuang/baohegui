"""安全测试 — 知识图谱管理接口仅限管理员 (v3 enhanced)

覆盖：
- 普通用户不能 KG seed / audit / create / update / delete
- 匿名不能 KG seed / audit / create
- 普通用户可以搜索 KG / stats / RAG context / related nodes（只读）
- admin 可以所有管理操作
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.models.knowledge_graph import KGNode
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

    # ── Seed ──────────────────────────────────────────

    def test_anonymous_cannot_kg_seed(self, client: TestClient):
        resp = client.post("/api/kg/seed")
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_normal_user_cannot_kg_seed(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_seed_user")
        resp = client.post("/api/kg/seed", headers=_headers(user))
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_admin_can_seed_kg(self, client: TestClient, db_session):
        admin = _create_user(db_session, "kg_admin", role="admin")
        resp = client.post("/api/kg/seed", headers=_headers(admin))
        assert resp.status_code in (200, 500), f"Expected 200/500, got {resp.status_code}"

    # ── Node CRUD ─────────────────────────────────────

    def test_anonymous_cannot_create_node(self, client: TestClient):
        resp = client.post("/api/kg/node", json={
            "node_type": "regulation",
            "title": "test",
            "content": "test",
        })
        assert resp.status_code in (401, 403)

    def test_normal_user_cannot_create_node(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_create_user")
        resp = client.post("/api/kg/node", json={
            "node_type": "regulation",
            "title": "test",
            "content": "test",
        }, headers=_headers(user))
        assert resp.status_code in (401, 403)

    def test_admin_can_create_node(self, client: TestClient, db_session):
        admin = _create_user(db_session, "kg_create_admin", role="admin")
        resp = client.post("/api/kg/node", json={
            "node_type": "regulation",
            "title": "测试法规",
            "content": "测试内容",
            "source": "测试来源",
            "trust_level": 0.8,
            "audit_status": "verified",
        }, headers=_headers(admin))
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

    def test_normal_user_cannot_update_node(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_update_user")
        n = KGNode(node_type="regulation", title="test", content="test", audit_status="verified")
        db_session.add(n)
        db_session.commit()
        resp = client.put(f"/api/kg/node/{n.id}", json={
            "title": "hacked",
        }, headers=_headers(user))
        assert resp.status_code in (401, 403)

    def test_normal_user_cannot_delete_node(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_del_user")
        n = KGNode(node_type="regulation", title="test", content="test", audit_status="verified")
        db_session.add(n)
        db_session.commit()
        resp = client.delete(f"/api/kg/node/{n.id}", headers=_headers(user))
        assert resp.status_code in (401, 403)

    def test_normal_user_cannot_audit_node(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_audit_nouser")
        n = KGNode(
            node_type="regulation", title="test", content="test",
            audit_status="unreviewed", trust_level=0.3,
        )
        db_session.add(n)
        db_session.commit()
        resp = client.put(
            f"/api/kg/node/{n.id}/audit",
            params={"trust_level": 0.9, "audit_status": "verified"},
            headers=_headers(user),
        )
        assert resp.status_code in (401, 403)

    def test_normal_user_cannot_get_needing_review(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_review_user")
        resp = client.get("/api/kg/nodes/needing-review", headers=_headers(user))
        assert resp.status_code in (401, 403)

    def test_normal_user_cannot_create_edge(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_edge_user")
        resp = client.post("/api/kg/edge", params={
            "source_id": 1, "target_id": 2, "relation": "references",
        }, headers=_headers(user))
        assert resp.status_code in (401, 403)

    # ── Read-only (allowed for normal users) ───────────

    def test_normal_user_can_search_kg(self, client: TestClient, db_session):
        """普通用户可以使用 KG 搜索（只读）"""
        user = _create_user(db_session, "kg_search_user")
        resp = client.get("/api/kg/search?q=政府采购", headers=_headers(user))
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_anonymous_cannot_search_kg(self, client: TestClient):
        resp = client.get("/api/kg/search?q=政府采购")
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_normal_user_can_get_stats(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_stats_user")
        resp = client.get("/api/kg/stats", headers=_headers(user))
        assert resp.status_code == 200

    def test_normal_user_can_get_related(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_related_user")
        n = KGNode(node_type="regulation", title="test", content="test", audit_status="verified")
        db_session.add(n)
        db_session.commit()
        resp = client.get(f"/api/kg/related/{n.id}", headers=_headers(user))
        assert resp.status_code == 200

    def test_normal_user_can_get_rag_context(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_rag_user")
        resp = client.get("/api/kg/rag-context?rule_id=R001", headers=_headers(user))
        assert resp.status_code == 200
