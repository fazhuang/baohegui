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


def _seed_edge(db, source_id: int, target_id: int, relation: str) -> KGEdge:
    from app.models.knowledge_graph import KGEdge
    e = KGEdge(source_id=source_id, target_id=target_id, relation=relation, weight=1.0)
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


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

        # 第二次 seed — 节点和边均已存在，必须完全幂等
        resp2 = client.post("/api/kg/seed", headers=_headers(admin))
        assert resp2.status_code == 200
        count2 = resp2.json()["count"]

        assert count2 == 0, f"Seed not idempotent: first={count1}, second={count2}"


class TestRuleIdAssociation:
    """rule_id → 法规/案例关联"""

    def test_rule_id_finds_regulation(self, client: TestClient, db_session):
        user = _create_user(db_session, "kg_rule_user")
        rule = _seed_node(db_session, title="R001: test rule", node_type="rule", rule_id="R001",
                          audit_status="verified", trust_level=0.8)
        reg = _seed_node(db_session, title="reference regulation", node_type="regulation")
        _seed_edge(db_session, rule.id, reg.id, "references")

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
        rule = _seed_node(db_session, title="R001: test rule", node_type="rule", rule_id="R001",
                          audit_status="verified", trust_level=0.8)
        case = _seed_node(db_session, title="test case", node_type="case",
                          audit_status="verified", trust_level=0.8)
        _seed_edge(db_session, rule.id, case.id, "demonstrated_by")

        resp = client.get("/api/kg/cases/R001", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["cases"]) >= 1

    def test_rag_context_excludes_rejected_target(self, client: TestClient, db_session):
        """target 节点被 rejected 时不应进入 RAG context"""
        user = _create_user(db_session, "kg_rag_reject_user")
        rule = _seed_node(db_session, title="R001: test rule", node_type="rule", rule_id="R001",
                          audit_status="verified", trust_level=0.8)
        reg_rejected = _seed_node(
            db_session, title="rejected regulation", node_type="regulation",
            audit_status="rejected",
        )
        reg_good = _seed_node(
            db_session, title="good regulation", node_type="regulation",
            audit_status="verified", trust_level=0.9,
        )
        _seed_edge(db_session, rule.id, reg_rejected.id, "references")
        _seed_edge(db_session, rule.id, reg_good.id, "references")

        resp = client.get("/api/kg/rag-context", params={"rule_id": "R001"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        # rejected target 不应出现
        for ctx in data["contexts"]:
            assert ctx["title"] != "rejected regulation"

    def test_rag_context_excludes_low_trust_target(self, client: TestClient, db_session):
        """target 节点 trust < 0.3 时不应进入 RAG context"""
        user = _create_user(db_session, "kg_rag_low_user")
        rule = _seed_node(db_session, title="R001: test rule", node_type="rule", rule_id="R001",
                          audit_status="verified", trust_level=0.8)
        reg_low = _seed_node(
            db_session, title="low trust regulation", node_type="regulation",
            audit_status="verified", trust_level=0.1,
        )
        reg_good = _seed_node(
            db_session, title="good regulation", node_type="regulation",
            audit_status="verified", trust_level=0.8,
        )
        _seed_edge(db_session, rule.id, reg_low.id, "references")
        _seed_edge(db_session, rule.id, reg_good.id, "references")

        resp = client.get("/api/kg/rag-context", params={"rule_id": "R001"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        # 低trust (<0.3) target 不应出现
        for ctx in data["contexts"]:
            assert ctx["trust_level"] >= 0.3, f"Low trust context leaked: {ctx}"

    # ── Phase 2: rule 起点自身也必须可信 ──

    def test_rag_context_rejected_rule_returns_empty(self, client: TestClient, db_session):
        """rejected rule → verified regulation，不得返回 context"""
        user = _create_user(db_session, "kg_rag_rej_rule")
        rule = _seed_node(db_session, title="R001: rejected rule", node_type="rule",
                          rule_id="R001", audit_status="rejected", trust_level=0.8)
        reg = _seed_node(db_session, title="good regulation", node_type="regulation",
                         audit_status="verified", trust_level=0.9)
        _seed_edge(db_session, rule.id, reg.id, "references")

        resp = client.get("/api/kg/rag-context", params={"rule_id": "R001"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["contexts"]) == 0, (
            f"Rejected rule should not produce RAG context, got {data['contexts']}"
        )

    def test_rag_context_low_trust_rule_returns_empty(self, client: TestClient, db_session):
        """low trust rule (0.1) → verified regulation，不得返回 context"""
        user = _create_user(db_session, "kg_rag_low_rule")
        rule = _seed_node(db_session, title="R001: low trust rule", node_type="rule",
                          rule_id="R001", audit_status="verified", trust_level=0.1)
        reg = _seed_node(db_session, title="good regulation", node_type="regulation",
                         audit_status="verified", trust_level=0.9)
        _seed_edge(db_session, rule.id, reg.id, "references")

        resp = client.get("/api/kg/rag-context", params={"rule_id": "R001"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["contexts"]) == 0, (
            f"Low trust rule should not produce RAG context, got {data['contexts']}"
        )

    def test_rag_context_high_trust_rule_to_high_trust_regulation(self, client: TestClient, db_session):
        """verified high trust rule → verified high trust regulation，正常返回"""
        user = _create_user(db_session, "kg_rag_ok")
        rule = _seed_node(db_session, title="R001: trusted rule", node_type="rule",
                          rule_id="R001", audit_status="verified", trust_level=0.9)
        reg = _seed_node(db_session, title="trusted regulation", node_type="regulation",
                         audit_status="verified", trust_level=0.9)
        _seed_edge(db_session, rule.id, reg.id, "references")

        resp = client.get("/api/kg/rag-context", params={"rule_id": "R001"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["contexts"]) >= 1, f"Should return context, got empty"
        assert data["contexts"][0]["title"] == "trusted regulation"

    def test_find_regulation_by_rule_id_rejected_rule(self, client: TestClient, db_session):
        """find_regulation_for_rule 对 rejected rule 应返回空"""
        user = _create_user(db_session, "kg_reg_rej")
        rule = _seed_node(db_session, title="R001: rejected rule", node_type="rule",
                          rule_id="R001", audit_status="rejected", trust_level=0.8)
        reg = _seed_node(db_session, title="good reg", node_type="regulation",
                         audit_status="verified", trust_level=0.9)
        _seed_edge(db_session, rule.id, reg.id, "references")

        resp = client.get("/api/kg/regulation/R001", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["regulations"]) == 0, (
            f"Rejected rule should not link to regulations, got {data['regulations']}"
        )

    def test_find_cases_by_rule_id_low_trust_rule(self, client: TestClient, db_session):
        """find_cases_for_rule 对 low trust rule 应返回空"""
        user = _create_user(db_session, "kg_cases_low")
        rule = _seed_node(db_session, title="R001: low rule", node_type="rule",
                          rule_id="R001", audit_status="verified", trust_level=0.05)
        case = _seed_node(db_session, title="good case", node_type="case",
                          audit_status="verified", trust_level=0.8)
        _seed_edge(db_session, rule.id, case.id, "demonstrated_by")

        resp = client.get("/api/kg/cases/R001", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["cases"]) == 0, (
            f"Low trust rule should not link to cases, got {data['cases']}"
        )


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

    def test_normal_user_cannot_query_rejected(self, client: TestClient, db_session):
        """普通用户传 audit_status=rejected 应返回 403"""
        user = _create_user(db_session, "kg_user_no_rej")
        _seed_node(db_session, title="r1", node_type="regulation", audit_status="rejected")
        resp = client.get("/api/kg/search", params={"q": "", "audit_status": "rejected"}, headers=_headers(user))
        assert resp.status_code == 403, f"Expected 403 for normal user querying rejected, got {resp.status_code}"

    def test_admin_can_query_rejected(self, client: TestClient, db_session):
        """admin 传 audit_status=rejected 可以看到 rejected 节点"""
        admin = _create_user(db_session, "kg_admin_rej", role="admin")
        _seed_node(db_session, title="visible", node_type="regulation", audit_status="verified")
        _seed_node(db_session, title="rejected_node", node_type="regulation", audit_status="rejected")
        resp = client.get("/api/kg/search", params={"q": "", "audit_status": "rejected"}, headers=_headers(admin))
        assert resp.status_code == 200
        data = resp.json()
        titles = [r["title"] for r in data["results"]]
        assert "rejected_node" in titles, f"Admin should see rejected, got {titles}"

    def test_admin_default_search_excludes_rejected(self, client: TestClient, db_session):
        """admin 默认搜索（不传 audit_status）也应排除 rejected"""
        admin = _create_user(db_session, "kg_admin_def", role="admin")
        _seed_node(db_session, title="visible", node_type="regulation", audit_status="verified")
        _seed_node(db_session, title="hidden", node_type="regulation", audit_status="rejected")
        resp = client.get("/api/kg/search", params={"q": ""}, headers=_headers(admin))
        assert resp.status_code == 200
        data = resp.json()
        titles = [r["title"] for r in data["results"]]
        assert "hidden" not in titles, f"Admin default search should exclude rejected, got {titles}"
        assert "visible" in titles


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

    def test_related_nodes_outgoing(self, client: TestClient, db_session):
        """默认 outgoing 方向：查 source_id == node_id"""
        user = _create_user(db_session, "kg_rel_user")
        src = _seed_node(db_session, title="source", node_type="rule")
        tgt = _seed_node(db_session, title="target", node_type="regulation")
        _seed_edge(db_session, src.id, tgt.id, "references")

        resp = client.get(f"/api/kg/related/{src.id}", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["related"]) >= 1
        rel = data["related"][0]
        assert rel["relation"] == "references"
        assert rel["node"]["title"] == "target"

    def test_related_nodes_incoming(self, client: TestClient, db_session):
        """incoming 方向：查 target_id == node_id — 谁引用了我"""
        user = _create_user(db_session, "kg_rel_in")
        rule = _seed_node(db_session, title="rule node", node_type="rule")
        reg = _seed_node(db_session, title="regulation node", node_type="regulation")
        _seed_edge(db_session, rule.id, reg.id, "references")

        # 从 regulation 角度查 incoming：应找到引用它的 rule
        resp = client.get(f"/api/kg/related/{reg.id}", params={"direction": "incoming"}, headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["related"]) >= 1, f"Expected incoming relation, got {data}"
        rel = data["related"][0]
        assert "←" in rel["relation"]  # flipped label
        assert rel["node"]["title"] == "rule node"

    def test_related_nodes_outgoing_no_results_for_target(self, client: TestClient, db_session):
        """outgoing 方向在 target 节点上查不到记录（因为边是从 rule→regulation）"""
        user = _create_user(db_session, "kg_rel_out")
        src = _seed_node(db_session, title="source rule", node_type="rule")
        tgt = _seed_node(db_session, title="target reg", node_type="regulation")
        _seed_edge(db_session, src.id, tgt.id, "references")

        # outgoing (默认) 从 target 看 → 没有 outgoing 边，应返回空
        resp = client.get(f"/api/kg/related/{tgt.id}", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["related"]) == 0, (
            f"Outgoing from target should be empty, got {data['related']}"
        )


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


# ═══════════════════════════════════════════════════════════════
# v5 新增测试 — 问题修复覆盖
# ═══════════════════════════════════════════════════════════════


class TestRagTraceableFields:
    """Issue #1: RAG 可追溯字段真正贯通"""

    def test_rag_context_has_source_url_and_dates(self, client: TestClient, db_session):
        """建 rule -> regulation references，regulation 带 source_url/effective_date/publish_date，
        build_rag_context 返回 source_url/effective_date/publish_date 原样保留"""
        from datetime import date
        user = _create_user(db_session, "kg_trace_user")

        reg = KGNode(
            node_type="regulation",
            title="测试法规-追溯验证",
            content="法规正文内容",
            source="财政部",
            source_url="https://law.example.gov/test-law",
            effective_date=date(2025, 1, 1),
            publish_date=date(2024, 12, 15),
            jurisdiction="全国",
            trust_level=0.8,
            audit_status="verified",
        )
        db_session.add(reg)
        db_session.commit()
        db_session.refresh(reg)

        rule = KGNode(
            node_type="rule",
            title="R099: trace test rule",
            content="测试规则正文",
            source="包合规规则库",
            rule_id="R099",
            trust_level=0.8,
            audit_status="verified",
        )
        db_session.add(rule)
        db_session.commit()
        db_session.refresh(rule)

        edge = KGEdge(source_id=rule.id, target_id=reg.id, relation="references", weight=1.0)
        db_session.add(edge)
        db_session.commit()

        resp = client.get(
            "/api/kg/rag-context",
            params={"rule_id": "R099"},
            headers=_headers(user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["context_count"] >= 1, f"Expected >=1 context, got {data}"

        ctx = data["contexts"][0]
        # 关键字段存在
        assert ctx["node_id"] is not None, f"node_id missing: {ctx}"
        assert ctx["source"] is not None, f"source missing: {ctx}"
        assert ctx["trust_level"] >= 0.3, f"trust_level too low: {ctx}"
        assert ctx["content"], f"content empty: {ctx}"
        assert ctx["relation"] == "references", f"relation wrong: {ctx}"
        assert ctx["edge_weight"] == 1.0, f"edge_weight wrong: {ctx}"
        # source_url 不为空字符串
        assert ctx["source_url"] == "https://law.example.gov/test-law", \
            f"source_url should be preserved, got '{ctx.get('source_url')}'"
        # 日期字段
        assert ctx["effective_date"] == "2025-01-01", \
            f"effective_date should be '2025-01-01', got '{ctx.get('effective_date')}'"
        assert ctx["publish_date"] == "2024-12-15", \
            f"publish_date should be '2024-12-15', got '{ctx.get('publish_date')}'"
        assert ctx["type"] == "regulation"

    def test_rag_context_source_url_none_for_missing(self, client: TestClient, db_session):
        """没有 source_url 的法规节点，RAG 返回 None（不伪造空字符串）"""
        user = _create_user(db_session, "kg_trace_none")

        reg = KGNode(
            node_type="regulation",
            title="无来源法规",
            content="内容",
            source="测试",
            # 无 source_url
            trust_level=0.8,
            audit_status="verified",
        )
        db_session.add(reg)
        db_session.commit()
        db_session.refresh(reg)

        rule = KGNode(
            node_type="rule",
            title="R098: no url rule",
            content="测试",
            source="test",
            rule_id="R098",
            trust_level=0.8,
            audit_status="verified",
        )
        db_session.add(rule)
        db_session.commit()
        db_session.refresh(rule)

        edge = KGEdge(source_id=rule.id, target_id=reg.id, relation="references", weight=1.0)
        db_session.add(edge)
        db_session.commit()

        resp = client.get(
            "/api/kg/rag-context",
            params={"rule_id": "R098"},
            headers=_headers(user),
        )
        assert resp.status_code == 200
        ctxs = resp.json()["contexts"]
        assert len(ctxs) >= 1
        # source_url 应为 None 而非空字符串
        assert ctxs[0].get("source_url") is None, \
            f"Expected None for missing source_url, got '{ctxs[0].get('source_url')}'"


class TestConceptExcludedFromRag:
    """Issue #2: 禁止 concept 进入 RAG 法规依据"""

    def test_rule_concept_references_not_in_rag(self, client: TestClient, db_session):
        """手工创建 rule -> concept references，/api/kg/rag-context 必须为空"""
        user = _create_user(db_session, "kg_concept_rag")

        concept = KGNode(
            node_type="concept",
            title="项目分类: 测试概念",
            content="概念内容",
            source="test",
            rule_id="CAT-TEST",
            trust_level=0.6,
            audit_status="verified",
        )
        db_session.add(concept)
        db_session.commit()
        db_session.refresh(concept)

        rule = KGNode(
            node_type="rule",
            title="R097: concept ref rule",
            content="测试",
            source="test",
            rule_id="R097",
            trust_level=0.8,
            audit_status="verified",
        )
        db_session.add(rule)
        db_session.commit()
        db_session.refresh(rule)

        # 创建 rule -> concept references (此 edge 只能通过直接 DB 插入，API 已拒绝)
        edge = KGEdge(source_id=rule.id, target_id=concept.id, relation="references", weight=1.0)
        db_session.add(edge)
        db_session.commit()

        resp = client.get(
            "/api/kg/rag-context",
            params={"rule_id": "R097"},
            headers=_headers(user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["context_count"] == 0, \
            f"Concept should not enter RAG as regulation reference, got {data['contexts']}"

    def test_admin_cannot_create_references_to_concept(self, client: TestClient, db_session):
        """admin 尝试创建 rule -> concept references，必须返回 422"""
        admin = _create_user(db_session, "kg_concept_admin", role="admin")

        concept = KGNode(
            node_type="concept",
            title="概念节点",
            content="概念内容",
            source="test",
            trust_level=0.6,
            audit_status="verified",
        )
        db_session.add(concept)
        db_session.commit()
        db_session.refresh(concept)

        rule = KGNode(
            node_type="rule",
            title="规则节点",
            content="规则内容",
            source="test",
            trust_level=0.8,
            audit_status="verified",
        )
        db_session.add(rule)
        db_session.commit()
        db_session.refresh(rule)

        resp = client.post("/api/kg/edge", params={
            "source_id": rule.id,
            "target_id": concept.id,
            "relation": "references",
            "weight": 1.0,
        }, headers=_headers(admin))
        assert resp.status_code == 422, \
            f"Expected 422 for references to concept, got {resp.status_code}: {resp.text}"

    def test_concept_search_by_type(self, client: TestClient, db_session):
        """/api/kg/search?node_type=concept&q=项目分类 能返回概念节点"""
        user = _create_user(db_session, "kg_conc_search")

        concept = KGNode(
            node_type="concept",
            title="项目分类: 测试概念",
            content="概念内容",
            source="test",
            rule_id="CAT-TEST",
            trust_level=0.6,
            audit_status="verified",
        )
        db_session.add(concept)
        db_session.commit()

        resp = client.get(
            "/api/kg/search",
            params={"node_type": "concept", "q": "项目分类"},
            headers=_headers(user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1, f"Expected concept in search results, got {data}"
        for r in data["results"]:
            assert r["node_type"] == "concept"


class TestDuplicateRuleIdEdgeSelection:
    """Issue #3: duplicate rule_id 选择有边节点"""

    def test_duplicate_rule_id_prefers_edged_node(self, client: TestClient, db_session):
        """同 rule_id 两个 verified rule，一个无边，一个有 references。
        rag-context 必须返回有边节点关联法规。"""
        user = _create_user(db_session, "kg_dup_rule")

        # Rule A: no edges
        rule_a = KGNode(
            node_type="rule",
            title="R096: no edge rule",
            content="无关联",
            source="test",
            rule_id="R096",
            trust_level=0.8,
            audit_status="verified",
        )
        db_session.add(rule_a)
        db_session.commit()
        db_session.refresh(rule_a)

        # Rule B: same rule_id, has references edge
        rule_b = KGNode(
            node_type="rule",
            title="R096: edged rule",
            content="有关联",
            source="test",
            rule_id="R096",
            trust_level=0.8,
            audit_status="verified",
        )
        db_session.add(rule_b)
        db_session.commit()
        db_session.refresh(rule_b)

        reg = KGNode(
            node_type="regulation",
            title="关联法规",
            content="法规内容",
            source="测试",
            trust_level=0.8,
            audit_status="verified",
        )
        db_session.add(reg)
        db_session.commit()
        db_session.refresh(reg)

        edge = KGEdge(source_id=rule_b.id, target_id=reg.id, relation="references", weight=1.0)
        db_session.add(edge)
        db_session.commit()

        resp = client.get(
            "/api/kg/rag-context",
            params={"rule_id": "R096"},
            headers=_headers(user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["context_count"] >= 1, \
            f"Should return context from edged node, got {data}"
        # The regulation title should come through
        ctx = data["contexts"][0]
        assert ctx["title"] == "关联法规", \
            f"Expected regulation from edged rule, got {ctx['title']}"


class TestPagination:
    """Issue #3: 分页"""

    def test_pagination_120_nodes(self, client: TestClient, db_session):
        """创建 120 个节点，limit=50 offset=0 返回 50 + total=120。
        offset=50 返回下一页。"""
        user = _create_user(db_session, "kg_page_user")

        for i in range(120):
            n = KGNode(
                node_type="regulation",
                title=f"Page Test Regulation #{i:04d}",
                content=f"content {i}",
                source="test",
                audit_status="verified",
                trust_level=0.8,
            )
            db_session.add(n)
        db_session.commit()

        # Page 1
        resp = client.get(
            "/api/kg/search",
            params={"q": "Page Test", "limit": 50, "offset": 0},
            headers=_headers(user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 120, f"Expected total=120, got {data['total']}"
        assert data["limit"] == 50
        assert data["offset"] == 0
        assert len(data["results"]) == 50, f"Expected 50 results, got {len(data['results'])}"

        # Page 2
        resp2 = client.get(
            "/api/kg/search",
            params={"q": "Page Test", "limit": 50, "offset": 50},
            headers=_headers(user),
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["results"]) == 50, f"Expected 50 results on page 2, got {len(data2['results'])}"

        # Page 3 (should have 20 left)
        resp3 = client.get(
            "/api/kg/search",
            params={"q": "Page Test", "limit": 50, "offset": 100},
            headers=_headers(user),
        )
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert len(data3["results"]) == 20, f"Expected 20 results on page 3, got {len(data3['results'])}"


class TestEdgeValidation:
    """Issue #3: 边创建校验"""

    def test_illegal_relation_returns_422(self, client: TestClient, db_session):
        """非法 relation 返回 422（FastAPI 参数校验）"""
        admin = _create_user(db_session, "kg_illegal_admin", role="admin")

        src = KGNode(
            node_type="regulation", title="src", content="c",
            audit_status="verified",
        )
        tgt = KGNode(
            node_type="regulation", title="tgt", content="c",
            audit_status="verified",
        )
        db_session.add_all([src, tgt])
        db_session.commit()
        db_session.refresh(src)
        db_session.refresh(tgt)

        resp = client.post("/api/kg/edge", params={
            "source_id": src.id,
            "target_id": tgt.id,
            "relation": "INVALID_RELATION",
            "weight": 1.0,
        }, headers=_headers(admin))
        assert resp.status_code == 422, \
            f"Expected 422 for illegal relation, got {resp.status_code}: {resp.text}"

    def test_duplicate_edge_returns_duplicate_flag(self, client: TestClient, db_session):
        """重复创建同一 edge 不重复插入，返回 duplicate=true"""
        admin = _create_user(db_session, "kg_dup_edge_admin", role="admin")

        src = KGNode(
            node_type="regulation", title="dup_src", content="c",
            audit_status="verified",
        )
        tgt = KGNode(
            node_type="regulation", title="dup_tgt", content="c",
            audit_status="verified",
        )
        db_session.add_all([src, tgt])
        db_session.commit()
        db_session.refresh(src)
        db_session.refresh(tgt)

        # 第一次：创建
        resp1 = client.post("/api/kg/edge", params={
            "source_id": src.id,
            "target_id": tgt.id,
            "relation": "related_to",
            "weight": 0.5,
        }, headers=_headers(admin))
        assert resp1.status_code == 201, f"First create should succeed, got {resp1.status_code}: {resp1.text}"
        assert not resp1.json().get("duplicate")

        # 第二次：重复 — 不插入
        resp2 = client.post("/api/kg/edge", params={
            "source_id": src.id,
            "target_id": tgt.id,
            "relation": "related_to",
            "weight": 0.5,
        }, headers=_headers(admin))
        assert resp2.status_code in (200, 201), f"Duplicate should return 200/201, got {resp2.status_code}: {resp2.text}"
        data2 = resp2.json()
        assert data2.get("duplicate") is True, f"Expected duplicate=true, got {data2}"


class TestComplaintCaseSync:
    """Issue #3: complaint_cases 表同步"""

    def test_complaint_case_table_exists(self, client: TestClient, db_session):
        """Alembic 迁移后表存在"""
        from sqlalchemy import inspect
        inspector = inspect(db_session.get_bind())
        tables = inspector.get_table_names()
        assert "complaint_cases" in tables, \
            f"complaint_cases table should exist, got tables: {tables}"

    def test_complaint_case_sync_creates_unreviewed_case_node(self, client: TestClient, db_session):
        """插入 ComplaintCase 后 seed 同步为 case 节点，audit_status=unreviewed，trust_level=0.55"""
        from app.models.complaint_case import ComplaintCase

        cc = ComplaintCase(
            province="甘肃",
            title="测试投诉案例-同步验证",
            project_name="测试项目",
            decision_type="upheld",
            complaint_types='["品牌锁定", "参数排他"]',
            legal_basis='["政府采购法第二十条"]',
            summary="这是一个测试投诉案例",
            is_analyzed=1,
        )
        db_session.add(cc)
        db_session.commit()
        db_session.refresh(cc)

        # Seed — 应由 ComplaintCase 创建对应 KGNode
        from app.services.knowledge_graph import knowledge_graph
        knowledge_graph.seed_builtin_knowledge(db_session)

        # 查找新同步的节点
        from app.models.knowledge_graph import KGNode
        synced = db_session.query(KGNode).filter(
            KGNode.rule_id == f"CC-{cc.id}",
            KGNode.node_type == "case",
        ).first()

        assert synced is not None, f"ComplaintCase should be synced to KG case node"
        assert synced.audit_status == "unreviewed", \
            f"Synced case should be unreviewed, got {synced.audit_status}"
        assert synced.trust_level == 0.55, \
            f"Synced case trust_level should be 0.55, got {synced.trust_level}"
        assert synced.node_type == "case"

    def test_unreviewed_complaint_case_not_in_rag(self, client: TestClient, db_session):
        """unreviewed complaint case 节点不进入 RAG"""
        from app.models.complaint_case import ComplaintCase

        user = _create_user(db_session, "kg_cc_rag_user")

        cc = ComplaintCase(
            province="宁夏",
            title="未审核投诉案例",
            project_name="测试项目2",
            decision_type="upheld",
            complaint_types='["品牌锁定"]',
            summary="未审核案例不应进入RAG",
            is_analyzed=1,
        )
        db_session.add(cc)
        db_session.commit()
        db_session.refresh(cc)

        from app.services.knowledge_graph import knowledge_graph
        knowledge_graph.seed_builtin_knowledge(db_session)

        # 先验证节点存在
        from app.models.knowledge_graph import KGNode
        synced = db_session.query(KGNode).filter(
            KGNode.rule_id == f"CC-{cc.id}",
            KGNode.node_type == "case",
        ).first()
        assert synced is not None, "Synced node must exist"
        assert synced.audit_status == "unreviewed"

        # 尝试用相似案例搜索 — unreviewed case 不应被返回
        resp = client.get(
            "/api/kg/similar-cases",
            params={"desc": "品牌锁定", "limit": 5},
            headers=_headers(user),
        )
        assert resp.status_code == 200
        for c in resp.json()["cases"]:
            assert c["id"] != synced.id, \
                f"Unreviewed case should not appear in similar cases: {c}"

    def test_sync_complaint_cases_is_idempotent_and_sanitized(self, db_session):
        """complaint_cases 同步到 KG 时应幂等，并保留脱敏后的展示内容"""
        from app.models.complaint_case import ComplaintCase
        from app.models.knowledge_graph import KGNode
        from app.services.knowledge_graph import knowledge_graph

        cc = ComplaintCase(
            province="甘肃",
            title="测试投诉案例-同步去重",
            project_name="测试项目",
            project_number="GS-2026-001",
            complainant="某公司联系人张三",
            respondent="某采购人",
            decision_date="2026-06-18",
            decision_type="upheld",
            complaint_types='["品牌锁定", "参数排他"]',
            legal_basis='["政府采购法第二十条"]',
            summary="这是一个测试投诉案例",
            raw_content="原始全文不应进入 KG 展示内容",
            is_analyzed=1,
        )
        db_session.add(cc)
        db_session.commit()
        db_session.refresh(cc)

        first_count = knowledge_graph.sync_complaint_cases(db_session)
        assert first_count == 1

        synced = db_session.query(KGNode).filter(
            KGNode.rule_id == f"CC-{cc.id}",
            KGNode.node_type == "case",
        ).first()
        assert synced is not None
        assert synced.audit_status == "unreviewed"
        assert synced.trust_level == 0.55
        assert synced.publish_date is not None
        assert "投诉人" not in synced.content
        assert "某公司联系人张三" not in synced.content
        assert "项目编号: GS-2026-001" in synced.content

        second_count = knowledge_graph.sync_complaint_cases(db_session)
        assert second_count == 0


class TestRagTrustedFilters:
    """Issue #3: RAG 可信过滤 — 补缺口"""

    def test_rejected_target_not_in_rag(self, client: TestClient, db_session):
        """rejected target 不进入 RAG（已有验证，确认保留）"""
        user = _create_user(db_session, "kg_rag_rej_target")
        rule = KGNode(
            node_type="rule", title="R001: rej target rule", content="t",
            rule_id="R001", audit_status="verified", trust_level=0.8, source="test",
        )
        reg_rej = KGNode(
            node_type="regulation", title="rejected reg", content="t",
            audit_status="rejected", source="test", trust_level=0.8,
        )
        reg_ok = KGNode(
            node_type="regulation", title="ok reg", content="t",
            audit_status="verified", trust_level=0.8, source="test",
        )
        db_session.add_all([rule, reg_rej, reg_ok])
        db_session.commit()
        db_session.refresh(rule)
        db_session.refresh(reg_rej)
        db_session.refresh(reg_ok)
        db_session.add(KGEdge(source_id=rule.id, target_id=reg_rej.id, relation="references"))
        db_session.add(KGEdge(source_id=rule.id, target_id=reg_ok.id, relation="references"))
        db_session.commit()

        resp = client.get("/api/kg/rag-context", params={"rule_id": "R001"}, headers=_headers(user))
        assert resp.status_code == 200
        ctxs = resp.json()["contexts"]
        titles = [c["title"] for c in ctxs]
        assert "rejected reg" not in titles, f"Rejected target leaked: {titles}"
        assert "ok reg" in titles

    def test_low_trust_target_not_in_rag(self, client: TestClient, db_session):
        """low-trust target (0.1) 不进入 RAG"""
        user = _create_user(db_session, "kg_rag_target_low")
        rule = KGNode(
            node_type="rule", title="R001: low target rule", content="t",
            rule_id="R001", audit_status="verified", trust_level=0.8, source="test",
        )
        reg_low = KGNode(
            node_type="regulation", title="low trust reg", content="t",
            audit_status="verified", trust_level=0.1, source="test",
        )
        reg_ok = KGNode(
            node_type="regulation", title="ok reg", content="t",
            audit_status="verified", trust_level=0.8, source="test",
        )
        db_session.add_all([rule, reg_low, reg_ok])
        db_session.commit()
        db_session.refresh(rule)
        db_session.refresh(reg_low)
        db_session.refresh(reg_ok)
        db_session.add(KGEdge(source_id=rule.id, target_id=reg_low.id, relation="references"))
        db_session.add(KGEdge(source_id=rule.id, target_id=reg_ok.id, relation="references"))
        db_session.commit()

        resp = client.get("/api/kg/rag-context", params={"rule_id": "R001"}, headers=_headers(user))
        assert resp.status_code == 200
        for ctx in resp.json()["contexts"]:
            assert ctx["trust_level"] >= 0.3, f"Low trust target leaked: {ctx}"

    def test_rejected_rule_not_in_rag(self, client: TestClient, db_session):
        """rejected rule 不进入 RAG"""
        user = _create_user(db_session, "kg_rag_rej_rule2")
        rule = KGNode(
            node_type="rule", title="R001: rej rule", content="t",
            rule_id="R001", audit_status="rejected", trust_level=0.8, source="test",
        )
        reg = KGNode(
            node_type="regulation", title="good reg", content="t",
            audit_status="verified", trust_level=0.9, source="test",
        )
        db_session.add_all([rule, reg])
        db_session.commit()
        db_session.refresh(rule)
        db_session.refresh(reg)
        db_session.add(KGEdge(source_id=rule.id, target_id=reg.id, relation="references"))
        db_session.commit()

        resp = client.get("/api/kg/rag-context", params={"rule_id": "R001"}, headers=_headers(user))
        assert resp.status_code == 200
        assert len(resp.json()["contexts"]) == 0, \
            f"Rejected rule should not produce RAG context"

    def test_low_trust_rule_not_in_rag(self, client: TestClient, db_session):
        """low-trust rule (0.1) 不进入 RAG"""
        user = _create_user(db_session, "kg_rag_low_rule2")
        rule = KGNode(
            node_type="rule", title="R001: low rule", content="t",
            rule_id="R001", audit_status="verified", trust_level=0.1, source="test",
        )
        reg = KGNode(
            node_type="regulation", title="good reg", content="t",
            audit_status="verified", trust_level=0.9, source="test",
        )
        db_session.add_all([rule, reg])
        db_session.commit()
        db_session.refresh(rule)
        db_session.refresh(reg)
        db_session.add(KGEdge(source_id=rule.id, target_id=reg.id, relation="references"))
        db_session.commit()

        resp = client.get("/api/kg/rag-context", params={"rule_id": "R001"}, headers=_headers(user))
        assert resp.status_code == 200
        assert len(resp.json()["contexts"]) == 0, \
            f"Low trust rule should not produce RAG context"


class TestRelatedNodeFields:
    """Issue #1: get_related 返回完整字段"""

    def test_related_node_has_traceable_fields(self, client: TestClient, db_session):
        """get_related 返回的 node 字典包含 source_url/jurisdiction/effective_date/publish_date/created_at"""
        from datetime import date
        user = _create_user(db_session, "kg_rel_fields_user")

        reg = KGNode(
            node_type="regulation",
            title="关联节点字段验证",
            content="完整字段测试",
            source="国务院",
            source_url="https://law.test/rel",
            jurisdiction="全国",
            effective_date=date(2024, 6, 1),
            publish_date=date(2024, 5, 15),
            trust_level=0.8,
            audit_status="verified",
        )
        db_session.add(reg)
        db_session.commit()
        db_session.refresh(reg)

        rule = KGNode(
            node_type="rule",
            title="关联字段发起节点",
            content="测试",
            source="test",
            rule_id="R095",
            trust_level=0.8,
            audit_status="verified",
        )
        db_session.add(rule)
        db_session.commit()
        db_session.refresh(rule)

        edge = KGEdge(source_id=rule.id, target_id=reg.id, relation="references", weight=0.9)
        db_session.add(edge)
        db_session.commit()

        resp = client.get(f"/api/kg/related/{rule.id}", headers=_headers(user))
        assert resp.status_code == 200
        related = resp.json()["related"]
        assert len(related) >= 1
        node = related[0]["node"]

        assert node.get("source_url") == "https://law.test/rel", \
            f"source_url mismatch: {node.get('source_url')}"
        assert node.get("jurisdiction") == "全国", \
            f"jurisdiction mismatch: {node.get('jurisdiction')}"
        assert node.get("effective_date") == "2024-06-01", \
            f"effective_date mismatch: {node.get('effective_date')}"
        assert node.get("publish_date") == "2024-05-15", \
            f"publish_date mismatch: {node.get('publish_date')}"
        assert node.get("created_at") is not None, f"created_at should not be None"


class TestCrawlerTriggerEnhancements:
    """crawler trigger 返回值增强 + 管理接口"""

    def test_trigger_return_has_scrape_stats(self, client: TestClient, db_session):
        """POST /api/crawler/trigger 返回 scrape_stats 字段（即使采集量为0）"""
        admin = _create_user(db_session, "c_trigger_admin", role="admin")
        resp = client.post("/api/crawler/trigger", headers=_headers(admin))
        # 200 = 调度器成功执行（即使没有外部网络），500 = 调度器内部错误
        assert resp.status_code in (200, 500)
        data = resp.json()
        # 成功时应有 scrape_stats
        if resp.status_code == 200:
            assert "scrape_stats" in data, f"trigger response missing scrape_stats: {data}"
            ss = data["scrape_stats"]
            assert isinstance(ss, dict)
            for key in ("ccgp", "ningxia", "shaanxi", "mof", "cases_saved", "kg_synced"):
                assert key in ss, f"scrape_stats missing key: {key}"

    def test_status_has_scrape_summary(self, client: TestClient, db_session):
        """GET /api/crawler/status 含 last_case_scrape 摘要和 kg_sync_summary"""
        user = _create_user(db_session, "c_status_user")
        resp = client.get("/api/crawler/status", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert "last_case_scrape" in data
        assert "kg_sync_summary" in data
        # kg_sync_summary 可能为 null（从未采集过）
        if data["kg_sync_summary"] is not None:
            assert "last_synced_count" in data["kg_sync_summary"]

    def test_needing_review_has_admin_fields(self, client: TestClient, db_session):
        """GET /api/kg/nodes/needing-review 返回字段含 source/jurisdiction/rule_id/complaint_case_id"""
        admin = _create_user(db_session, "c_review_admin", role="admin")

        # 创建一个 unreviewed 案例节点（模拟 sync_complaint_cases 输出）
        import json as _json_mod
        node = KGNode(
            node_type="case",
            title="[甘肃] 测试未审核案例",
            content="项目名称: 测试\n处理结果: 投诉成立",
            source="甘肃政府采购网",
            source_url="https://example.com/case1",
            tags="案例,投诉案例,投诉成立,品牌锁定",
            jurisdiction="甘肃",
            rule_id="CC-999",
            trust_level=0.55,
            audit_status="unreviewed",
            metadata_json=_json_mod.dumps({
                "complaint_case_id": 999,
                "decision_type": "upheld",
                "complaint_types": ["品牌锁定"],
            }),
        )
        db_session.add(node)
        db_session.commit()

        resp = client.get("/api/kg/nodes/needing-review", headers=_headers(admin))
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "total" in data
        assert data["total"] >= 1
        n = data["nodes"][0]
        for field in ("id", "node_type", "title", "source", "jurisdiction",
                      "rule_id", "trust_level", "audit_status", "tags",
                      "content_preview", "complaint_case_id", "decision_type"):
            assert field in n, f"needing-review node missing field: {field}"


class TestComplaintCasesIndexes:
    """迁移索引存在 + 幂等"""

    def test_complaint_cases_indexes_present(self, client: TestClient, db_session):
        """Alembic 索引迁移后所有目标索引都存在"""
        from sqlalchemy import inspect
        inspector = inspect(db_session.get_bind())
        indexes = {idx["name"] for idx in inspector.get_indexes("complaint_cases")}
        expected = {
            "ix_complaint_cases_source_url",
            "ix_complaint_cases_decision_type",
            "ix_complaint_cases_province",
            "ix_complaint_cases_is_analyzed",
            "ix_complaint_cases_created_at",
        }
        missing = expected - indexes
        assert not missing, f"Missing indexes on complaint_cases: {missing}"
