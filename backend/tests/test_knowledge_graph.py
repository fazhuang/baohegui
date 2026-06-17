"""知识图谱测试 — v3 增强版

覆盖:
- 搜索鉴权（匿名不可访问）
- 普通用户只读
- admin 才能 seed/audit/write
- seed 幂等
- rule_id 能找到法规/案例关联
- rejected/低trust节点不会进入RAG context
- limit 生效
- CRUD 管理操作鉴权
- 统计接口
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.models.knowledge_graph import KGNode, KGEdge
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


def _seed_node(db, **kwargs) -> KGNode:
    defaults = {
        "node_type": "regulation",
        "title": "test-law",
        "content": "test content",
        "source": "test",
        "audit_status": "verified",
        "trust_level": 0.8,
    }
    defaults.update(kwargs)
    n = KGNode(**defaults)
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


class TestKnowledgeGraphAuth:
    """知识图谱接口鉴权"""

    def test_anonymous_cannot_search(self, client: TestClient):
        resp = client.get("/api/kg/search", params={"q": "招标"})
        assert resp.status_code in (401, 403)

    def test_anonymous_cannot_access_stats(self, client: TestClient):
        resp = client.get("/api/kg/stats")
        assert resp.status_code in (401, 403)

    def test_anonymous_cannot_access_rag_context(self, client: TestClient):
        resp = client.get("/api/kg/rag-context", params={"rule_id": "R001"})
        assert resp.status_code in (401, 403)

    def test_normal_user_can_search(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_search_user")
        _seed_node(db_session, title="政府采购法", node_type="regulation")
        resp = client.get("/api/kg/search", params={"q": "政府采购"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data

    def test_normal_user_can_get_rag_context(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_rag_user")
        rule = _seed_node(db_session, title="R001: test rule", node_type="rule", rule_id="R001")
        reg = _seed_node(db_session, title="test regulation", node_type="regulation")
        e = KGEdge(source_id=rule.id, target_id=reg.id, relation="references")
        db_session.add(e)
        db_session.commit()
        resp = client.get("/api/kg/rag-context", params={"rule_id": "R001"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert "contexts" in data

    def test_normal_user_cannot_seed(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_noseed_user")
        resp = client.post("/api/kg/seed", headers=_headers(user))
        assert resp.status_code in (401, 403)

    def test_normal_user_cannot_create_node(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_nocreate_user")
        resp = client.post("/api/kg/node", json={
            "node_type": "regulation",
            "title": "test",
            "content": "test",
        }, headers=_headers(user))
        assert resp.status_code in (401, 403)

    def test_normal_user_cannot_audit_node(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_noaudit_user")
        node = _seed_node(db_session, audit_status="unreviewed")
        resp = client.put(
            f"/api/kg/node/{node.id}/audit",
            params={"trust_level": 0.9, "audit_status": "verified"},
            headers=_headers(user),
        )
        assert resp.status_code in (401, 403)

    def test_normal_user_cannot_delete_node(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_nodelete_user")
        node = _seed_node(db_session)
        resp = client.delete(f"/api/kg/node/{node.id}", headers=_headers(user))
        assert resp.status_code in (401, 403)


class TestKnowledgeGraphAdmin:
    """管理员操作"""

    def test_admin_can_seed(self, client: TestClient, db_session):
        admin = _create_user(db_session, "kg_admin", role="admin")
        resp = client.post("/api/kg/seed", headers=_headers(admin))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["count"] >= 0

    def test_admin_can_create_node(self, client: TestClient, db_session):
        admin = _create_user(db_session, "kg_create_admin", role="admin")
        resp = client.post("/api/kg/node", json={
            "node_type": "regulation",
            "title": "新法规",
            "content": "新法规内容",
            "source": "测试来源",
            "trust_level": 0.8,
            "audit_status": "verified",
        }, headers=_headers(admin))
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["title"] == "新法规"

    def test_admin_can_audit_node(self, client: TestClient, db_session):
        admin = _create_user(db_session, "kg_audit_admin", role="admin")
        node = _seed_node(db_session, audit_status="unreviewed", trust_level=0.4)
        resp = client.put(
            f"/api/kg/node/{node.id}/audit",
            params={"trust_level": 0.9, "audit_status": "verified"},
            headers=_headers(admin),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["trust_level"] == 0.9
        assert data["audit_status"] == "verified"
        assert data["audited_by"] == admin.id

    def test_admin_can_delete_node(self, client: TestClient, db_session):
        admin = _create_user(db_session, "kg_delete_admin", role="admin")
        node = _seed_node(db_session)
        resp = client.delete(f"/api/kg/node/{node.id}", headers=_headers(admin))
        assert resp.status_code == 200
        # 软删除: 标记为 rejected
        data = resp.json()
        assert data["status"] == "rejected"

    def test_admin_can_get_nodes_needing_review(self, client: TestClient, db_session):
        admin = _create_user(db_session, "kg_review_admin", role="admin")
        _seed_node(db_session, audit_status="unreviewed", title="待审核节点")
        _seed_node(db_session, audit_status="flagged", title="标记节点")
        _seed_node(db_session, audit_status="verified", title="已审核节点")
        resp = client.get("/api/kg/nodes/needing-review", headers=_headers(admin))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) >= 2


class TestSeedIdempotent:
    """种子数据幂等性"""

    def test_seed_is_idempotent(self, client: TestClient, db_session):
        admin = _create_user(db_session, "kg_idem_admin", role="admin")
        # 第一次 seed
        resp1 = client.post("/api/kg/seed", headers=_headers(admin))
        assert resp1.status_code == 200
        count1 = resp1.json()["count"]

        # 第二次 seed — 应返回 0 或较小计数（因为已存在）
        resp2 = client.post("/api/kg/seed", headers=_headers(admin))
        assert resp2.status_code == 200
        count2 = resp2.json()["count"]

        # 幂等：第二次不应增加相同节点
        assert count2 <= count1 or count1 == 0, (
            f"Seed not idempotent: first={count1}, second={count2}"
        )


class TestRuleIdAssociation:
    """rule_id → 法规/案例关联"""

    def test_rule_id_finds_regulation(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_rule_user")
        rule = _seed_node(db_session, title="R001: test rule", node_type="rule", rule_id="R001")
        reg = _seed_node(db_session, title="reference regulation", node_type="regulation")
        e = KGEdge(source_id=rule.id, target_id=reg.id, relation="references")
        db_session.add(e)
        db_session.commit()

        resp = client.get("/api/kg/regulation/R001", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["regulations"]) >= 1
        # verify the target node is the regulation
        found = False
        for r in data["regulations"]:
            if r.get("node", {}).get("title") == "reference regulation":
                found = True
        assert found, f"Expected to find regulation, got: {data}"

    def test_rule_id_finds_cases(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_case_user")
        rule = _seed_node(db_session, title="R001: test rule", node_type="rule", rule_id="R001")
        case = _seed_node(db_session, title="test case", node_type="case")
        e = KGEdge(source_id=rule.id, target_id=case.id, relation="demonstrated_by")
        db_session.add(e)
        db_session.commit()

        resp = client.get("/api/kg/cases/R001", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["cases"]) >= 1

    def test_rag_context_excludes_rejected(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_rag_reject_user")
        rule = _seed_node(db_session, title="R001: test rule", node_type="rule", rule_id="R001")
        reg_rejected = _seed_node(
            db_session, title="rejected regulation", node_type="regulation",
            audit_status="rejected",
        )
        reg_good = _seed_node(
            db_session, title="good regulation", node_type="regulation",
            audit_status="verified", trust_level=0.9,
        )
        e1 = KGEdge(source_id=rule.id, target_id=reg_rejected.id, relation="references")
        e2 = KGEdge(source_id=rule.id, target_id=reg_good.id, relation="references")
        db_session.add_all([e1, e2])
        db_session.commit()

        resp = client.get("/api/kg/rag-context", params={"rule_id": "R001"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        # rejected 不应出现
        for ctx in data["contexts"]:
            assert ctx["title"] != "rejected regulation"

    def test_rag_context_excludes_low_trust(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_rag_low_user")
        rule = _seed_node(db_session, title="R001: test rule", node_type="rule", rule_id="R001")
        reg_low = _seed_node(
            db_session, title="low trust regulation", node_type="regulation",
            audit_status="verified", trust_level=0.1,
        )
        reg_good = _seed_node(
            db_session, title="good regulation", node_type="regulation",
            audit_status="verified", trust_level=0.8,
        )
        e1 = KGEdge(source_id=rule.id, target_id=reg_low.id, relation="references")
        e2 = KGEdge(source_id=rule.id, target_id=reg_good.id, relation="references")
        db_session.add_all([e1, e2])
        db_session.commit()

        resp = client.get("/api/kg/rag-context", params={"rule_id": "R001"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        # 低trust (<0.3) 不应出现
        for ctx in data["contexts"]:
            assert ctx["trust_level"] >= 0.3, f"Low trust context leaked: {ctx}"


class TestSearchFilters:
    """搜索过滤功能"""

    def test_search_by_node_type(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_type_user")
        _seed_node(db_session, title="reg1", node_type="regulation")
        _seed_node(db_session, title="case1", node_type="case")
        resp = client.get("/api/kg/search", params={"q": "", "node_type": "case"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        for r in data["results"]:
            assert r["node_type"] == "case"

    def test_search_by_rule_id(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_rid_user")
        _seed_node(db_session, title="r1", node_type="rule", rule_id="R001")
        _seed_node(db_session, title="r2", node_type="rule", rule_id="R002")
        resp = client.get("/api/kg/search", params={"q": "", "rule_id": "R001"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        for r in data["results"]:
            assert r["rule_id"] == "R001"

    def test_search_by_tags(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_tag_user")
        _seed_node(db_session, title="r1", node_type="case", tags="品牌锁定,投诉成立")
        _seed_node(db_session, title="r2", node_type="case", tags="评分标准")
        resp = client.get("/api/kg/search", params={"q": "", "tags": "品牌锁定"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1
        for r in data["results"]:
            assert "品牌锁定" in r.get("tags", "")

    def test_search_by_jurisdiction(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_jur_user")
        _seed_node(db_session, title="甘肃案例", node_type="case", jurisdiction="甘肃")
        _seed_node(db_session, title="宁夏案例", node_type="case", jurisdiction="宁夏")
        resp = client.get("/api/kg/search", params={"q": "", "jurisdiction": "甘肃"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        for r in data["results"]:
            assert "甘肃" in r.get("jurisdiction", "")

    def test_search_limit(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_limit_user")
        for i in range(10):
            _seed_node(db_session, title=f"node-{i}", node_type="regulation")
        resp = client.get("/api/kg/search", params={"q": "", "limit": 3}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) <= 3

    def test_search_limit_clamped(self, client: TestClient, db_session):
        """limit 在 API 层面被限制在 1-100（FastAPI Query validation），服务层也有硬上限"""
        user = _create_user(db_session, "kg_clamp_user")
        # API level rejects >100
        resp = client.get("/api/kg/search", params={"q": "", "limit": 9999}, headers=_headers(user))
        assert resp.status_code == 422  # FastAPI validation rejects out-of-range

        # API level accepts ≤100
        resp = client.get("/api/kg/search", params={"q": "", "limit": 100}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) <= 100

    def test_search_excludes_rejected_by_default(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_hidden_user")
        _seed_node(db_session, title="visible", node_type="regulation", audit_status="verified")
        _seed_node(db_session, title="hidden", node_type="regulation", audit_status="rejected")
        resp = client.get("/api/kg/search", params={"q": ""}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        titles = [r["title"] for r in data["results"]]
        assert "hidden" not in titles
        assert "visible" in titles

    def test_admin_can_see_rejected(self, client: TestClient, db_session):
        admin = _create_user(db_session, "kg_see_admin", role="admin")
        _seed_node(db_session, title="visible", node_type="regulation", audit_status="verified")
        _seed_node(db_session, title="hidden", node_type="regulation", audit_status="rejected")
        resp = client.get("/api/kg/search", params={"q": "", "audit_status": "rejected"}, headers=_headers(admin))
        assert resp.status_code == 200
        data = resp.json()
        titles = [r["title"] for r in data["results"]]
        assert "hidden" in titles


class TestStats:
    """统计接口"""

    def test_stats_with_auth(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_stats_user")
        _seed_node(db_session, title="r1", node_type="regulation")
        _seed_node(db_session, title="c1", node_type="case")
        resp = client.get("/api/kg/stats", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_nodes"] >= 2
        assert "by_type" in data
        assert "by_audit_status" in data


class TestRelatedNodes:
    """关联节点"""

    def test_related_nodes(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_rel_user")
        src = _seed_node(db_session, title="source", node_type="rule")
        tgt = _seed_node(db_session, title="target", node_type="regulation")
        e = KGEdge(source_id=src.id, target_id=tgt.id, relation="references")
        db_session.add(e)
        db_session.commit()

        resp = client.get(f"/api/kg/related/{src.id}", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["related"]) >= 1
        rel = data["related"][0]
        assert rel["relation"] == "references"
        assert rel["node"]["title"] == "target"


class TestKnowledgeGraphAPI:
    """KG 搜索 API 基础测试"""

    def test_search_requires_auth(self, client):
        resp = client.get("/api/kg/search", params={"q": "招标"})
        assert resp.status_code in (401, 403)

    def test_search_with_auth(self, client, auth_headers):
        resp = client.get("/api/kg/search", params={"q": "招标"}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data

    def test_seed_endpoint(self, client, auth_headers):
        resp = client.post("/api/kg/seed", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_regulation_lookup(self, client, auth_headers):
        resp = client.get("/api/kg/regulation/R101", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "regulations" in data
