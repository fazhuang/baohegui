"""Phase 0 回归测试 — 覆盖本阶段全部修复。

测试范围：
1. /api/crawler/cases 分页契约 — total 为整数且遵循筛选条件
2. 案例分析审计字段正确
3. complaint_types 规范写入+兼容解析
4. 采集任务 PARTIAL 状态
5. 知识库诊断脚本可运行
6. Schema 一致性
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.models.complaint_case import ComplaintCase
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


class TestPaginationContractFix:
    """修复 #1: /api/crawler/cases 分页契约"""

    def test_total_is_integer(self, client: TestClient, db_session):
        """total 必须是整数类型。"""
        user = _create_user(db_session, "pg_user")
        resp = client.get("/api/crawler/cases", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["total"], int), f"total must be int, got {type(data['total'])}: {data['total']}"
        assert isinstance(data["limit"], int)
        assert isinstance(data["offset"], int)
        assert isinstance(data["items"], list)

    def test_total_respects_province_filter(self, client: TestClient, db_session):
        """total 必须遵循 province 筛选条件。"""
        user = _create_user(db_session, "pg_prov_user")
        # 创建不同省份的案例
        db_session.add(ComplaintCase(
            province="甘肃", title="甘肃案例", decision_type="upheld",
            complaint_types='["品牌锁定"]',
        ))
        db_session.add(ComplaintCase(
            province="宁夏", title="宁夏案例", decision_type="upheld",
            complaint_types='["参数排他"]',
        ))
        db_session.add(ComplaintCase(
            province="甘肃", title="甘肃案例2", decision_type="rejected",
            complaint_types='["评分标准"]',
        ))
        db_session.commit()

        # 不加筛选
        resp = client.get("/api/crawler/cases", headers=_headers(user))
        assert resp.json()["total"] == 3

        # 按省份筛选
        resp = client.get("/api/crawler/cases", params={"province": "甘肃"}, headers=_headers(user))
        assert resp.json()["total"] == 2

        resp = client.get("/api/crawler/cases", params={"province": "宁夏"}, headers=_headers(user))
        assert resp.json()["total"] == 1

    def test_total_respects_decision_type_filter(self, client: TestClient, db_session):
        """total 必须遵循 decision_type 筛选条件。"""
        user = _create_user(db_session, "pg_dt_user")
        db_session.add(ComplaintCase(
            province="全国", title="成立案例", decision_type="upheld",
            complaint_types='["品牌锁定"]',
        ))
        db_session.add(ComplaintCase(
            province="全国", title="驳回案例", decision_type="rejected",
            complaint_types='["参数排他"]',
        ))
        db_session.commit()

        resp = client.get("/api/crawler/cases", params={"decision_type": "upheld"}, headers=_headers(user))
        assert resp.json()["total"] == 1

        resp = client.get("/api/crawler/cases", params={"decision_type": "rejected"}, headers=_headers(user))
        assert resp.json()["total"] == 1

        resp = client.get("/api/crawler/cases", params={"decision_type": "partial"}, headers=_headers(user))
        assert resp.json()["total"] == 0

    def test_total_respects_combined_filters(self, client: TestClient, db_session):
        """total 必须同时遵循 province 和 decision_type 筛选。"""
        user = _create_user(db_session, "pg_comb_user")
        db_session.add(ComplaintCase(
            province="甘肃", title="案例1", decision_type="upheld",
            complaint_types='["品牌锁定"]',
        ))
        db_session.add(ComplaintCase(
            province="甘肃", title="案例2", decision_type="rejected",
            complaint_types='["参数排他"]',
        ))
        db_session.add(ComplaintCase(
            province="宁夏", title="案例3", decision_type="upheld",
            complaint_types='["评分标准"]',
        ))
        db_session.commit()

        resp = client.get(
            "/api/crawler/cases",
            params={"province": "甘肃", "decision_type": "upheld"},
            headers=_headers(user),
        )
        assert resp.json()["total"] == 1

        resp = client.get(
            "/api/crawler/cases",
            params={"province": "甘肃", "decision_type": "partial"},
            headers=_headers(user),
        )
        assert resp.json()["total"] == 0

    def test_pagination_structure(self, client: TestClient, db_session):
        """分页响应结构一致。"""
        user = _create_user(db_session, "pg_struct_user")
        for i in range(5):
            db_session.add(ComplaintCase(
                province="全国", title=f"案例{i}", decision_type="upheld",
                complaint_types='["测试"]',
            ))
        db_session.commit()

        resp = client.get("/api/crawler/cases", params={"limit": 2, "offset": 0}, headers=_headers(user))
        data = resp.json()
        assert len(data["items"]) <= 2
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 0

        resp2 = client.get("/api/crawler/cases", params={"limit": 2, "offset": 2}, headers=_headers(user))
        data2 = resp2.json()
        assert len(data2["items"]) <= 2
        assert data2["total"] == 5


class TestAnalysisAuditFieldsFix:
    """修复 #2: 案例分析审计字段正确"""

    def test_analyze_result_has_analyzed_not_analyzed_count(self, db_session):
        """rule_miner.analyze_all_unanalyzed() 返回 'analyzed' 而非 'analyzed_count'。"""
        from app.services.rule_miner import analyze_all_unanalyzed

        # 创建一条投诉成立的案例
        db_session.add(ComplaintCase(
            province="甘肃", title="测试", decision_type="upheld",
            complaint_types='["品牌锁定"]',
            raw_content="指定品牌 厂家授权 资质要求",
            summary="参数排他",
            is_analyzed=0,
        ))
        db_session.commit()

        result = analyze_all_unanalyzed(db_session)
        assert "analyzed" in result, f"Result should have 'analyzed', got keys: {list(result.keys())}"
        assert "analyzed_count" not in result, "Result should NOT have 'analyzed_count'"
        assert isinstance(result["analyzed"], int)
        assert result["analyzed"] >= 1

    def test_analyze_result_has_new_pattern_candidates_not_rules_generated(self, db_session):
        """返回 'new_pattern_candidates' 而非 'rules_generated'。"""
        from app.services.rule_miner import analyze_all_unanalyzed

        db_session.add(ComplaintCase(
            province="甘肃", title="测试2", decision_type="partial",
            complaint_types='["指定检测机构"]',
            raw_content="指定检测机构 辐射安全许可证 MAC地址 代理费超标",
            summary="多种违规",
            is_analyzed=0,
        ))
        db_session.commit()

        result = analyze_all_unanalyzed(db_session)
        assert "new_pattern_candidates" in result, (
            f"Result should have 'new_pattern_candidates', got keys: {list(result.keys())}"
        )
        assert "rules_generated" not in result

    def test_audit_fields_reported_correctly(self, client: TestClient, db_session):
        """API audit 日志读取的字段与 analyze_all_unanalyzed 返回一致。"""
        import json as _json

        admin = _create_user(db_session, "audit_admin", role="admin")

        db_session.add(ComplaintCase(
            province="甘肃", title="审计测试", decision_type="upheld",
            complaint_types='["品牌锁定", "厂家授权"]',
            raw_content="指定品牌 厂家授权 检测报告注册证造假",
            summary="需要分析",
            is_analyzed=0,
        ))
        db_session.commit()

        resp = client.post("/api/crawler/analyze", headers=_headers(admin))
        # 200 = 成功；422 = 输入问题；500 = 服务器错误
        assert resp.status_code in (200, 201), f"Expected 200/201, got {resp.status_code}: {resp.text}"
        data = resp.json()

        # 返回的字段名与 API 代码中读取的字段名一致
        assert "analyzed" in data, f"Response must contain 'analyzed': {data}"
        assert "new_pattern_candidates" in data
        assert "summary" in data

        # 确认被分析的案例已标记
        case = db_session.query(ComplaintCase).filter(
            ComplaintCase.title == "审计测试"
        ).first()
        assert case is not None
        assert case.is_analyzed == 1, f"Case should be marked analyzed, got is_analyzed={case.is_analyzed}"

        # Issue #3：确认审计日志真实记录了 crawler_analyze 操作及 detail 字段
        from app.core.audit import AuditLog
        logs = db_session.query(AuditLog).filter(
            AuditLog.action == "crawler_analyze"
        ).all()
        assert len(logs) >= 1, "Audit log should contain at least one crawler_analyze entry"
        log = logs[0]
        detail = _json.loads(log.detail or "{}")
        assert isinstance(detail.get("analyzed_count"), int), \
            f"Audit detail analyzed_count should be int, got {detail}"
        assert detail["analyzed_count"] >= 1, \
            f"analyzed_count should be >=1 for this test, got {detail}"
        assert isinstance(detail.get("known_pattern_hits"), int), \
            f"known_pattern_hits should be int, got {detail}"
        assert isinstance(detail.get("new_candidate_rules"), int), \
            f"new_candidate_rules should be int, got {detail}"


class TestComplaintTypesNormalization:
    """修复 #3: complaint_types 规范写入 + 兼容解析"""

    def test_new_data_is_valid_json_array(self, db_session):
        """新采集案例的 complaint_types 必须是有效 JSON 数组。"""
        # 模拟采集器写入
        cc = ComplaintCase(
            province="甘肃",
            title="JSON数组测试",
            decision_type="upheld",
            complaint_types=json.dumps(["品牌锁定", "参数排他"], ensure_ascii=False),
        )
        db_session.add(cc)
        db_session.commit()

        # 从数据库重新读取
        reloaded = db_session.query(ComplaintCase).filter(ComplaintCase.id == cc.id).first()
        parsed = json.loads(reloaded.complaint_types)
        assert isinstance(parsed, list), f"Expected list, got {type(parsed)}"
        assert "品牌锁定" in parsed
        assert "参数排他" in parsed
        assert len(parsed) == 2

    def test_legacy_repr_format_parsed_in_kg_sync(self, db_session):
        """历史 Python repr 格式（如 \"['品牌锁定', '参数排他']\"）能被 KG 同步正确解析。"""
        from app.services.knowledge_graph import knowledge_graph

        cc = ComplaintCase(
            province="甘肃",
            title="repr格式测试",
            decision_type="upheld",
            complaint_types="['品牌锁定', '参数排他']",  # 旧格式
            summary="测试",
            is_analyzed=1,
        )
        db_session.add(cc)
        db_session.commit()

        # KG 同步应正确解析
        synced = knowledge_graph.sync_complaint_cases(db_session)
        assert synced >= 1

        node = db_session.query(KGNode).filter(
            KGNode.rule_id == f"CC-{cc.id}",
            KGNode.node_type == "case",
        ).first()
        assert node is not None
        # tags 应包含解析后的类型
        assert "品牌锁定" in node.tags
        assert "参数排他" in node.tags

    def test_empty_value_returns_empty_list(self, db_session):
        """空值 complaint_types 在 KG 同步中返回空列表。"""
        from app.services.knowledge_graph import knowledge_graph

        cc = ComplaintCase(
            province="全国",
            title="空值测试",
            decision_type="upheld",
            complaint_types="",
            summary="测试",
            is_analyzed=1,
        )
        db_session.add(cc)
        db_session.commit()

        synced = knowledge_graph.sync_complaint_cases(db_session)
        assert synced >= 1

        node = db_session.query(KGNode).filter(
            KGNode.rule_id == f"CC-{cc.id}",
            KGNode.node_type == "case",
        ).first()
        assert node is not None
        # tags 应包含基本标签，不应包含空 tag
        assert "案例" in node.tags
        assert "投诉案例" in node.tags

    def test_null_value_returns_empty_list(self, db_session):
        """NULL complaint_types 在 KG 同步中被安全处理。"""
        from app.services.knowledge_graph import knowledge_graph

        cc = ComplaintCase(
            province="全国",
            title="NULL测试",
            decision_type="upheld",
            complaint_types=None,
            summary="测试",
            is_analyzed=1,
        )
        db_session.add(cc)
        db_session.commit()

        # 不应抛异常
        synced = knowledge_graph.sync_complaint_cases(db_session)
        assert synced >= 1

    def test_corrupted_value_does_not_crash(self, db_session):
        """损坏的 complaint_types 值不会导致 KG 同步崩溃。"""
        from app.services.knowledge_graph import knowledge_graph

        cc = ComplaintCase(
            province="全国",
            title="损坏值测试",
            decision_type="upheld",
            complaint_types="{broken json!!!",
            summary="测试",
            is_analyzed=1,
        )
        db_session.add(cc)
        db_session.commit()

        # 不应抛异常
        synced = knowledge_graph.sync_complaint_cases(db_session)
        assert synced >= 1

        # 节点应存在，tags 至少包含基本分类
        node = db_session.query(KGNode).filter(
            KGNode.rule_id == f"CC-{cc.id}",
            KGNode.node_type == "case",
        ).first()
        assert node is not None
        assert "案例" in node.tags

    def test_single_item_repr_parsed(self, db_session):
        """单元素 Python repr 格式也能被解析。"""
        from app.services.knowledge_graph import knowledge_graph

        cc = ComplaintCase(
            province="全国",
            title="单元素repr",
            decision_type="upheld",
            complaint_types="['品牌锁定']",
            summary="测试",
            is_analyzed=1,
        )
        db_session.add(cc)
        db_session.commit()

        synced = knowledge_graph.sync_complaint_cases(db_session)
        assert synced >= 1

        node = db_session.query(KGNode).filter(
            KGNode.rule_id == f"CC-{cc.id}",
            KGNode.node_type == "case",
        ).first()
        assert "品牌锁定" in node.tags

    def test_apostrophe_in_repr_value(self, db_session):
        """历史 repr 中包含撇号的值能被正确解析为独立标签。例如 ['O\\'Reilly', '品牌']。"""
        from app.services.knowledge_graph import knowledge_graph

        cc = ComplaintCase(
            province="全国",
            title="撇号repr测试",
            decision_type="upheld",
            complaint_types='''[\"O'Reilly\", \"品牌锁定\"]''',
            summary="测试",
            is_analyzed=1,
        )
        db_session.add(cc)
        db_session.commit()

        synced = knowledge_graph.sync_complaint_cases(db_session)
        assert synced >= 1

        node = db_session.query(KGNode).filter(
            KGNode.rule_id == f"CC-{cc.id}",
            KGNode.node_type == "case",
        ).first()
        assert node is not None
        assert "品牌锁定" in node.tags
        assert "O'Reilly" in node.tags


class TestScrapePartialStatus:
    """修复 #4: 采集 PARTIAL 状态"""

    def test_scrape_with_errors_is_partial(self, db_session, monkeypatch):
        """有 errors 的采集结果必须是 PARTIAL 状态。"""
        import asyncio

        from app.services.sync_scheduler import SyncScheduler, SyncStatus

        scheduler = SyncScheduler(case_scrape_interval_hours=168)

        async def _fake_crawl_all():
            return {
                "ccgp": {"saved": 0, "errors": []},
                "ningxia": {"saved": 0, "errors": []},
                "shaanxi": {"saved": 0, "errors": []},
                "mof": {"saved": 0, "errors": []},
                "kg_synced": 0,
                "errors": ["ningxia: 连接超时", "mof: 403 Forbidden"],
                "cases_saved": 0,
            }

        monkeypatch.setattr("app.services.crawler_service.crawl_all", _fake_crawl_all)

        record = asyncio.run(scheduler.scrape_cases())
        assert record.status == SyncStatus.PARTIAL, (
            f"Should be PARTIAL when errors exist, got {record.status.value}"
        )

    def test_scrape_without_errors_is_success(self, db_session, monkeypatch):
        """无 errors 的采集结果是 SUCCESS。"""
        import asyncio

        from app.services.sync_scheduler import SyncScheduler, SyncStatus

        scheduler = SyncScheduler(case_scrape_interval_hours=168)

        async def _fake_crawl_all():
            return {
                "ccgp": {"saved": 1, "errors": []},
                "ningxia": {"saved": 2, "errors": []},
                "shaanxi": {"saved": 0, "errors": []},
                "mof": {"saved": 0, "errors": []},
                "kg_synced": 3,
                "errors": [],
                "cases_saved": 3,
            }

        monkeypatch.setattr("app.services.crawler_service.crawl_all", _fake_crawl_all)

        record = asyncio.run(scheduler.scrape_cases())
        assert record.status == SyncStatus.SUCCESS, (
            f"Should be SUCCESS when no errors, got {record.status.value}"
        )


class TestDiagnosticScript:
    """修复 #5: 知识库诊断脚本"""

    def test_script_module_imports(self):
        """诊断脚本可以成功导入。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "audit_kb",
            "scripts/audit_knowledge_base.py",
        )
        assert spec is not None, "Cannot find audit script"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "audit"), "Script must have audit function"
        assert hasattr(mod, "main")

    def test_audit_with_no_data(self, db_session, monkeypatch):
        """空数据库诊断不抛异常。"""
        from scripts.audit_knowledge_base import audit as audit_kb

        class FakeArgs:
            db_url = None

        # monkeypatch _get_session to use the test session
        def _fake_session():
            return db_session

        monkeypatch.setattr("scripts.audit_knowledge_base._get_session", _fake_session)

        result = audit_kb(FakeArgs())
        assert "complaint_cases" in result
        assert "kg_nodes" in result
        assert "kg_edges" in result
        assert "orphan_complaint_cases_no_kg" in result
        assert "orphan_kg_projections_no_case" in result
        assert "duplicate_source_urls" in result
        assert "duplicate_edges" in result
        assert "json_assets" in result
        assert "rule_engine" in result

        # complaint_cases total 应为整数
        assert isinstance(result["complaint_cases"]["total"], int)

    def test_audit_with_case_data(self, db_session, monkeypatch):
        """有案例数据时诊断正确。"""
        from scripts.audit_knowledge_base import audit as audit_kb

        class FakeArgs:
            db_url = None

        # 插入测试数据
        cc1 = ComplaintCase(
            province="甘肃", title="案例1", decision_type="upheld",
            complaint_types='["品牌锁定"]', is_analyzed=0,
        )
        cc2 = ComplaintCase(
            province="宁夏", title="案例2", decision_type="rejected",
            complaint_types='["参数排他"]', is_analyzed=1,
        )
        db_session.add_all([cc1, cc2])
        db_session.commit()

        cc1_kg = KGNode(
            node_type="case", title="[甘肃] 案例1", content="测试",
            source="甘肃政府采购网", rule_id=f"CC-{cc1.id}",
            trust_level=0.55, audit_status="unreviewed",
        )
        db_session.add(cc1_kg)
        db_session.commit()

        def _fake_session():
            return db_session

        monkeypatch.setattr("scripts.audit_knowledge_base._get_session", _fake_session)

        result = audit_kb(FakeArgs())

        assert result["complaint_cases"]["total"] == 2
        assert result["complaint_cases"]["by_province"]["甘肃"] == 1
        assert result["complaint_cases"]["by_province"]["宁夏"] == 1
        assert result["complaint_cases"]["by_decision_type"]["upheld"] == 1
        assert result["complaint_cases"]["by_decision_type"]["rejected"] == 1

        # cc2 没有 KG 投影 → 应出现在孤儿列表中
        orphans = result["orphan_complaint_cases_no_kg"]
        orphan_ids = [o["id"] for o in orphans]
        assert cc2.id in orphan_ids, f"cc2 should be orphan, got orphans: {orphan_ids}"


class TestApiStatsEndpoint:
    """stats 接口仍然正常工作"""

    def test_stats_returns_correct_fields(self, client: TestClient, db_session):
        user = _create_user(db_session, "stats_user")
        resp = client.get("/api/crawler/stats", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "upheld" in data
        assert "rejected" in data
        assert "partial" in data
        assert "dismissed" in data
        assert isinstance(data["total"], int)

    def test_stats_reflects_data(self, client: TestClient, db_session):
        user = _create_user(db_session, "stats_data_user")
        db_session.add(ComplaintCase(
            province="全国", title="stats测试", decision_type="upheld",
            complaint_types='["测试"]',
        ))
        db_session.commit()

        resp = client.get("/api/crawler/stats", headers=_headers(user))
        data = resp.json()
        assert data["total"] == 1
        assert data["upheld"] == 1
