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
