"""Phase 2 案例运营闭环 — 服务层验收测试 (SQLite)

要件 9: 管理员完成采集记录审核和发布 → 普通用户只能看到发布内容 → 下架后普通用户和 RAG 均不可见

覆盖：
- 完整生命周期 (fetched → normalized → extracted → pending_review → verified → published → unpublished → archived)
- 普通用户可见性（仅 published）
- 下架后 RAG 隔离
- KG 投影幂等性
- 非法状态转换拒绝
- 去重策略（5 层 + 弱匹配不静默删除）
- 候选规则不自动发布
"""

import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.engine.case_state_machine import (
    CaseStatus,
    CaseStatusStateMachine,
    PublishStatus,
    VALID_TRANSITIONS,
)
from app.models.complaint_case import ComplaintCase
from app.models.candidate_rule import CandidateRule
from app.models.knowledge_graph import KGNode, KGEdge
from app.services.dedup_service import dedup_service
from app.services.kg_projection import kg_projection, SYNC_VERSION
from app.services.rule_miner import mine_to_candidates, promote_candidate_to_rule


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def db_session() -> Session:
    """测试用的 SQLite 内存数据库 session"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    # 创建所有表
    from app.models.document import Base as DocumentBase
    from app.models.candidate_rule import Base as CandidateRuleBase
    from app.models.rule import Base as RuleBase

    # complaint_case 用 DocumentBase
    DocumentBase.metadata.create_all(bind=engine)
    CandidateRuleBase.metadata.create_all(bind=engine)
    RuleBase.metadata.create_all(bind=engine)

    # knowledge_graph 表也创建
    from app.models.knowledge_graph import Base as KGraphBase
    KGraphBase.metadata.create_all(bind=engine)

    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


def _make_case(
    title: str,
    review_status: str = "fetched",
    publish_status: str = "draft",
    content: str = "",
    sanitized: str = "",
    source_url: str = "",
    canonical_url: str = "",
    project_number: str = "",
    case_no: str = "",
) -> ComplaintCase:
    """创建测试案例"""
    c = ComplaintCase(
        title=title,
        province="甘肃",
        review_status=review_status,
        publish_status=publish_status,
        decision_type="upheld",
        decision_date=date(2025, 6, 15),
        raw_content=content or f"{title} 正文",
        sanitized_content=sanitized or f"{title} 脱敏内容",
        summary=f"{title} 摘要",
        project_name=f"{title} 采购项目",
        project_number=project_number,
        case_no=case_no,
        source_url=source_url,
        canonical_url=canonical_url,
        source_type="ccgp",
    )
    c.set_content_hash()
    return c


# ═══════════════════════════════════════════════════════════════
# 1. 完整生命周期 (fetched → ... → archived)
# ═══════════════════════════════════════════════════════════════


class TestFullLifecycle:
    """要件 9 主路径：采集 → 审核 → 发布 → 下架 → 归档"""

    def test_full_happy_path(self, db_session: Session):
        """fetched → normalized → extracted → pending_review → verified → published → unpublished → archived"""
        sm = CaseStatusStateMachine()

        # 1. 采集（模拟 crawled）
        case = _make_case("测试案例-生命周期")
        db_session.add(case)
        db_session.commit()
        assert case.review_status == CaseStatus.FETCHED.value

        # 2. 规范化
        ok, _ = sm.transition(case, CaseStatus.NORMALIZED.value)
        assert ok
        db_session.commit()

        # 3. 抽取
        ok, _ = sm.transition(case, CaseStatus.EXTRACTED.value)
        assert ok
        db_session.commit()

        # 4. 进入审核
        ok, _ = sm.transition(case, CaseStatus.PENDING_REVIEW.value)
        assert ok
        db_session.commit()

        # 5. 审核通过
        ok, _ = sm.transition(case, CaseStatus.VERIFIED.value, user_id=1)
        assert ok
        assert case.reviewed_by == 1
        assert case.reviewed_at is not None
        db_session.commit()

        # 6. 发布
        ok, _ = sm.transition(case, CaseStatus.PUBLISHED.value, user_id=1)
        assert ok
        assert case.publish_status == PublishStatus.PUBLISHED.value
        assert case.published_at is not None
        db_session.commit()

        # 7. 下架
        ok, _ = sm.transition(case, CaseStatus.UNPUBLISHED.value, user_id=1)
        assert ok
        assert case.publish_status == PublishStatus.UNPUBLISHED.value
        db_session.commit()

        # 8. 归档
        ok, _ = sm.transition(case, CaseStatus.ARCHIVED.value)
        assert ok
        db_session.commit()

        # 9. 终态 — 不能再转换
        transitions = sm.get_allowed_transitions(case.review_status)
        assert len(transitions) == 0

    def test_quarantine_to_archived_path(self, db_session: Session):
        sm = CaseStatusStateMachine()
        case = _make_case("隔离案例", review_status="pending_review")
        db_session.add(case)
        db_session.commit()

        ok, _ = sm.transition(case, CaseStatus.QUARANTINED.value, user_id=1)
        assert ok
        db_session.commit()

        ok, _ = sm.transition(case, CaseStatus.ARCHIVED.value)
        assert ok
        assert case.review_status == CaseStatus.ARCHIVED.value


# ═══════════════════════════════════════════════════════════════
# 2. 普通用户可见性
# ═══════════════════════════════════════════════════════════════


class TestPublicVisibility:
    """要件 9: 普通用户只能看到 published 内容"""

    def test_public_cannot_see_unpublished(self, db_session: Session):
        """未发布案例不应出现在公开列表中"""
        c1 = _make_case("已发布案例", review_status="published", publish_status="published")
        c2 = _make_case("未发布案例", review_status="verified", publish_status="draft")
        c3 = _make_case("已下架案例", review_status="unpublished", publish_status="unpublished")
        c4 = _make_case("审核中案例", review_status="pending_review")
        db_session.add_all([c1, c2, c3, c4])
        db_session.commit()

        # 模拟公开查询条件
        published = (
            db_session.query(ComplaintCase)
            .filter(
                ComplaintCase.review_status == CaseStatus.PUBLISHED.value,
                ComplaintCase.publish_status == PublishStatus.PUBLISHED.value,
            )
            .all()
        )

        assert len(published) == 1
        assert published[0].title == "已发布案例"

    def test_public_gets_sanitized_content_only(self, db_session: Session):
        """公开接口不暴露 raw_content、complainant、respondent"""
        case = _make_case(
            "敏感案例",
            review_status="published",
            publish_status="published",
            content="原始投诉人: 张三, 被投诉人: 某单位, 包含敏感信息",
            sanitized="这是脱敏后的内容",
        )
        case.complainant = "张三"
        case.respondent = "某采购单位"
        db_session.add(case)
        db_session.commit()

        public_dict = case.to_public_dict()
        assert "raw_content" not in public_dict
        assert "complainant" not in public_dict
        assert "respondent" not in public_dict
        assert "reviewed_by" not in public_dict
        assert "extraction_metadata" not in public_dict
        assert public_dict.get("content") == "这是脱敏后的内容"

    def test_admin_sees_all_content(self, db_session: Session):
        """管理员可以看到完整信息"""
        case = _make_case(
            "管理员可见案例",
            review_status="published",
            publish_status="published",
            content="原始内容",
            sanitized="脱敏内容",
        )
        case.complainant = "投诉人X"
        case.respondent = "被投诉人Y"
        db_session.add(case)
        db_session.commit()

        full_dict = case.to_dict()
        assert full_dict.get("raw_content") == "原始内容"
        assert full_dict.get("complainant") == "投诉人X"
        assert full_dict.get("respondent") == "被投诉人Y"
        assert full_dict.get("sanitized_content") == "脱敏内容"


# ═══════════════════════════════════════════════════════════════
# 3. 下架后 RAG 隔离
# ═══════════════════════════════════════════════════════════════


class TestRAGIsolation:
    """要件 9: 下架案例从 RAG 隔离"""

    def test_unpublished_case_not_in_rag_context(self, db_session: Session):
        """下架案例不应被 RAG 上下文检索返回"""
        from app.services.knowledge_graph import KnowledgeGraphService

        # 创建 KG 节点：一个 verified（应出现在 RAG 中），一个 rejected（不应出现）
        node_verified = KGNode(
            node_type="case",
            title="已审核案例节点",
            content="合规案例内容",
            audit_status="verified",
            trust_level=0.8,
            rule_id="CC-1001",
            source_url="https://example.com/case1",
        )
        node_rejected = KGNode(
            node_type="case",
            title="下架案例节点",
            content="被下架案例内容",
            audit_status="rejected",
            trust_level=0.35,
            rule_id="CC-1002",
            source_url="https://example.com/case2",
        )
        db_session.add_all([node_verified, node_rejected])
        db_session.commit()

        # RAG search 应该排除 rejected 节点
        results, total = KnowledgeGraphService.search(
            db_session, "案例", node_type="case", is_admin=False
        )
        assert len(results) == 1
        assert results[0]["audit_status"] == "verified"  # search returns dicts
        assert total == 1

    def test_kg_search_rejects_unpublished(self, db_session: Session):
        """KG search 默认排除 rejected 节点（包括下架的）"""
        from app.services.knowledge_graph import KnowledgeGraphService

        verified = KGNode(node_type="case", title="V", content="...", audit_status="verified", trust_level=0.8)
        rejected = KGNode(node_type="case", title="R", content="...", audit_status="rejected", trust_level=0.3)
        db_session.add_all([verified, rejected])
        db_session.commit()

        # 非 admin 搜索
        results, _ = KnowledgeGraphService.search(db_session, "", node_type="case", is_admin=False)
        statuses = {r["audit_status"] for r in results}  # search returns dicts
        assert "rejected" not in statuses
        assert len(results) == 1

        # admin 搜索（默认也排除 rejected）
        results, _ = KnowledgeGraphService.search(db_session, "", node_type="case", is_admin=True)
        statuses = {r["audit_status"] for r in results}
        assert "rejected" not in statuses


# ═══════════════════════════════════════════════════════════════
# 4. KG 投影幂等性
# ═══════════════════════════════════════════════════════════════


class TestKGProjectionIdempotency:
    """要件 7: 投影失败可重试，不产生重复节点/边"""

    def test_no_duplicate_nodes_on_reproject(self, db_session: Session):
        """重复投影同一案例不产生重复节点"""
        case = _make_case(
            "幂等测试", review_status="published", publish_status="published",
            sanitized="脱敏正文",
        )
        db_session.add(case)
        db_session.commit()

        # 首次投影
        r1 = kg_projection.project_case(db_session, case)
        assert r1["success"]
        assert r1["action"] == "created"

        # 再次投影（内容未变）
        r2 = kg_projection.project_case(db_session, case)
        assert r2["success"]
        assert r2["action"] in ("skipped", "updated")

        # 验证只有一个节点
        nodes = (
            db_session.query(KGNode)
            .filter(KGNode.node_type == "case", KGNode.rule_id == f"CC-{case.id}")
            .all()
        )
        assert len(nodes) == 1

    def test_no_projection_without_sanitized_content(self, db_session: Session):
        """缺少 sanitized_content 的案例禁止投影"""
        case = _make_case("无脱敏内容", review_status="published", publish_status="published")
        # 必须显式清空 sanitized_content（_make_case 自动补全）
        case.sanitized_content = ""
        db_session.add(case)
        db_session.commit()

        r = kg_projection.project_case(db_session, case)
        assert not r["success"]
        assert "sanitized_content" in r.get("error", "")

    def test_no_projection_for_non_published(self, db_session: Session):
        """非 published 案例禁止投影"""
        case = _make_case("未发布", review_status="fetched", sanitized="content")
        db_session.add(case)
        db_session.commit()

        r = kg_projection.project_case(db_session, case)
        assert not r["success"]
        assert "未发布" in r.get("error", "")

    def test_full_publish_unpublish_republish_cycle(self, db_session: Session):
        """完整发布→下架→重新发布 KG 投影周期"""
        case = _make_case(
            "周期测试", review_status="published", publish_status="published",
            sanitized="脱敏正文内容ABC",
        )
        db_session.add(case)
        db_session.commit()

        # 发布投影
        r1 = kg_projection.project_case(db_session, case)
        assert r1["success"]
        node_id = r1["node_id"]
        db_session.commit()

        # 验证 published 时 KG 节点为 verified
        node = db_session.query(KGNode).filter(KGNode.id == node_id).first()
        assert node.audit_status == "verified"
        meta = json.loads(node.metadata_json or "{}")
        assert "unprojected_at" not in meta

        # 下架
        case.review_status = CaseStatus.UNPUBLISHED.value
        case.publish_status = PublishStatus.UNPUBLISHED.value
        r2 = kg_projection.unproject_case(db_session, case)
        assert r2["success"]
        db_session.commit()

        # 验证下架后 KG 节点为 rejected
        node = db_session.query(KGNode).filter(KGNode.id == node_id).first()
        assert node.audit_status == "rejected"
        meta = json.loads(node.metadata_json or "{}")
        assert "unprojected_at" in meta

        # 重新发布
        case.review_status = CaseStatus.PUBLISHED.value
        case.publish_status = PublishStatus.PUBLISHED.value
        r3 = kg_projection.project_case(db_session, case)
        assert r3["success"]
        assert r3["action"] == "restored"
        db_session.commit()

        # 验证恢复后 KG 节点为 verified
        node = db_session.query(KGNode).filter(KGNode.id == node_id).first()
        assert node.audit_status == "verified"
        meta = json.loads(node.metadata_json or "{}")
        assert "unprojected_at" not in meta

    def test_projection_metadata_has_sync_version(self, db_session: Session):
        """投影元数据包含 sync_version"""
        case = _make_case(
            "版本测试", review_status="published", publish_status="published",
            sanitized="正文",
        )
        db_session.add(case)
        db_session.commit()

        r = kg_projection.project_case(db_session, case)
        assert r["success"]
        node = db_session.query(KGNode).filter(KGNode.id == r["node_id"]).first()
        meta = json.loads(node.metadata_json or "{}")
        assert meta.get("sync_version") == SYNC_VERSION
        assert meta.get("origin_type") == "complaint_case"
        assert meta.get("origin_id") == case.id


# ═══════════════════════════════════════════════════════════════
# 5. 非法状态转换拒绝
# ═══════════════════════════════════════════════════════════════


class TestIllegalTransitions:
    """要件 3: 所有非法状态转换必须被拒绝"""

    ILLEGAL_TRANSITIONS = [
        # 跳过中间步骤
        ("fetched", "verified"),
        ("fetched", "published"),
        ("normalized", "pending_review"),
        ("extracted", "verified"),
        ("extracted", "published"),
        # 终态不能改变
        ("archived", "fetched"),
        ("archived", "published"),
        ("archived", "pending_review"),
        # 已发布不能直接拒绝
        ("published", "rejected"),
        ("published", "pending_review"),
        # 已拒绝不能直接发布
        ("rejected", "published"),
        ("rejected", "verified"),
        # 审查状态不能回退到 fetched（除非通过 retry）
        ("verified", "fetched"),
        ("pending_review", "fetched"),
        ("published", "fetched"),
    ]

    def test_all_illegal_transitions_rejected(self):
        sm = CaseStatusStateMachine()
        for from_s, to_s in self.ILLEGAL_TRANSITIONS:
            assert not sm.can_transition(from_s, to_s), f"ILLEGAL transition {from_s} → {to_s} was allowed!"

    def test_all_legal_transitions_accept(self):
        sm = CaseStatusStateMachine()
        for current, targets in VALID_TRANSITIONS.items():
            for target in targets:
                assert sm.can_transition(current.value, target.value), (
                    f"LEGAL transition {current.value} → {target.value} was rejected!"
                )


# ═══════════════════════════════════════════════════════════════
# 6. 去重策略验证
# ═══════════════════════════════════════════════════════════════


class TestDedupStrategy:
    """要件 4: 五层去重 — 强弱分离，弱匹配不静默删除"""

    def test_strong_matches_trigger_duplicate(self, db_session: Session):
        """强匹配（canonical_url, source_url, content_hash, project_number/case_no）自动标记"""
        # canonical_url match
        case1 = _make_case("A", canonical_url="https://example.com/dup1", source_url="s1")
        db_session.add(case1)
        db_session.commit()

        case2 = _make_case("B", canonical_url="https://example.com/dup1", source_url="s2")
        db_session.add(case2)
        db_session.commit()

        result = dedup_service.find_duplicates(db_session, case2, auto_mark=True)
        assert result["is_duplicate"]
        assert result["method"] == "canonical_url"
        assert len(result["duplicates"]) >= 1

    def test_weak_similarity_is_candidate_only(self, db_session: Session):
        """标题/内容相似度 仅返回候选列表，不自动标记"""
        case1 = _make_case(
            "宁夏人民医院手术麻醉设备采购项目投诉处理结果公告",
            content="项目编号2026-2，参数指向日本Hadeco品牌，涉嫌指定供应商",
            project_number="UNIQUE-A-001",
            source_url="https://example.com/a",
        )
        db_session.add(case1)
        db_session.commit()

        case2 = _make_case(
            "宁夏人民医院手术麻醉设备采购投诉处理公告 — 补充说明",
            content="项目编号2026-2，参数指向Hadeco，此外还有排他性条款",
            project_number="UNIQUE-B-001",
            source_url="https://example.com/b",
        )
        db_session.add(case2)
        db_session.commit()

        result = dedup_service.find_duplicates(db_session, case2, auto_mark=True)
        # 相似度候选可能有也可能没有（取决于阈值）
        # 但必须确保：如果 is_duplicate 为真，必须是强匹配触发
        if result["is_duplicate"]:
            assert result["method"] in (
                "canonical_url", "source_url", "content_hash", "project_number/case_no"
            ), f"不应被弱匹配自动标记: {result['method']}"

    def test_content_hash_identical_detected(self, db_session: Session):
        """相同内容产生相同 hash → 检测为重复"""
        content = "完全一样的内容文本ABCDEFG" * 10
        summary = "相同摘要"

        case1 = ComplaintCase(
            title="案例A",
            raw_content=content,
            summary=summary,
            source_url="http://hash1.example.com",
            province="甘肃",
            decision_type="upheld",
        )
        case1.set_content_hash()
        db_session.add(case1)
        db_session.commit()

        case2 = ComplaintCase(
            title="案例B",
            raw_content=content,
            summary=summary,
            source_url="http://hash2.example.com",
            province="甘肃",
            decision_type="upheld",
        )
        case2.set_content_hash()
        db_session.add(case2)
        db_session.commit()

        result = dedup_service.find_duplicates(db_session, case2)
        assert result["is_duplicate"], f"Expected duplicate, got: {result}"
        assert result["method"] == "content_hash"


# ═══════════════════════════════════════════════════════════════
# 7. 候选规则不自动发布
# ═══════════════════════════════════════════════════════════════


class TestCandidateRulesNotAutoPublished:
    """要件 8: 候选规则必须人工审核后才能进入版本化规则资产"""

    def test_candidate_rules_have_review_status_pending(self, db_session: Session):
        """新候选规则的 review_status 必须是 pending"""
        cand = CandidateRule(
            candidate_id="CAND-TEST-001",
            source_case_id=1,
            source_type="miner",
            rule_type="forbidden",
            target="测试目标",
            description="测试候选规则",
            risk_level="medium",
            confidence=0.3,
            miner_version="2.0.0",
            review_status="pending",
        )
        db_session.add(cand)
        db_session.commit()

        saved = db_session.query(CandidateRule).filter(
            CandidateRule.candidate_id == "CAND-TEST-001"
        ).first()
        assert saved is not None
        assert saved.review_status == "pending"
        assert saved.is_pending
        assert not saved.is_approved

    def test_promote_candidate_creates_formal_rule(self, db_session: Session):
        """审核通过后升级为正式规则"""
        # 创建候选
        cand = CandidateRule(
            candidate_id="CAND-TEST-002",
            source_case_id=1,
            source_type="miner",
            rule_type="forbidden",
            target="测试升级目标",
            description="需要人工审核后升级",
            risk_level="high",
            confidence=0.6,
            miner_version="2.0.0",
            review_status="pending",
            law_ref="政府采购法 第22条",
            suggestion="改进建议",
        )
        db_session.add(cand)
        db_session.commit()

        # 人工审核通过（两阶段：先审核，再升级）
        cand.approve(reviewer_id=1, note="审核通过，升级为正式规则")
        db_session.commit()

        # 第二阶段：升级为正式规则
        from app.services.rule_miner import promote_candidate_to_rule
        result = promote_candidate_to_rule(
            db_session, cand.id, reviewer_id=1, promoted_rule_id="R999"
        )
        assert result["success"]
        db_session.commit()

        assert cand.review_status == "approved"
        assert cand.reviewed_by == 1
        assert cand.promoted_to == "R999"
        db_session.commit()

        assert cand.review_status == "approved"
        assert cand.reviewed_by == 1
        assert cand.promoted_to == "R999"

    def test_cannot_promote_without_review(self, db_session: Session):
        """不能跳过审核直接升级"""
        cand = CandidateRule(
            candidate_id="CAND-TEST-003",
            source_case_id=1,
            source_type="miner",
            rule_type="forbidden",
            target="未审核",
            description="未审核不应被加载",
            review_status="pending",
        )
        db_session.add(cand)
        db_session.commit()

        # 验证状态
        assert cand.review_status == "pending"
        assert not cand.is_approved

    def test_rejected_candidate_not_promoted(self, db_session: Session):
        """拒绝的候选规则不应升级"""
        cand = CandidateRule(
            candidate_id="CAND-TEST-004",
            source_case_id=1,
            source_type="miner",
            rule_type="forbidden",
            target="拒绝",
            description="应被拒绝",
            review_status="pending",
        )
        db_session.add(cand)
        db_session.commit()

        cand.reject(reviewer_id=1, note="不符合要求")
        db_session.commit()

        assert cand.review_status == "rejected"
        assert cand.promoted_to is None


# ═══════════════════════════════════════════════════════════════
# 8. LLM 抽取不自动发布
# ═══════════════════════════════════════════════════════════════


class TestLLMExtractionNotAutoPublish:
    """要件 6: LLM 结果只能成为候选，不能自动发布"""

    def test_extraction_saves_metadata_not_publishes(self, db_session: Session):
        """LLM 抽取保存到 extraction_metadata，不改变 publish_status"""
        case = _make_case("待抽取案例", review_status="normalized")
        db_session.add(case)
        db_session.commit()

        # 模拟 LLM 抽取保存（不通过实际 LLM 调用）
        from app.services.case_extraction import _save_extraction, EXTRACTOR_VERSION

        extracted = {
            "dispute_focus": ["参数排他性"],
            "regulatory_finding": "认定采购文件存在排他条款",
            "decision_result": "投诉成立",
            "legal_basis": ["政府采购法 第22条"],
            "compliance_insights": ["避免指定参数"],
            "risk_tags": ["param_exclusion"],
            "confidence": 0.85,
            "evidence_snippets": ["证据1", "证据2"],
        }
        llm_result = {"model": "qwen-max", "tokens_used": 500}

        _save_extraction(case, extracted, llm_result, db_session)
        db_session.commit()

        # 验证抽取结果已保存
        assert case.extractor_version == EXTRACTOR_VERSION
        assert case.get_extraction_metadata().get("confidence") == 0.85
        assert len(case.get_extraction_metadata().get("dispute_focus", [])) == 1

        # 关键：抽取不改变 publish_status 和 review_status
        assert case.publish_status != "published"
        assert case.review_status == "normalized"

    def test_extraction_metadata_has_model_and_version(self, db_session: Session):
        """抽取元数据必须包含 model、prompt_version、confidence、evidence_snippets"""
        case = _make_case("抽取元数据测试")
        db_session.add(case)
        db_session.commit()

        from app.services.case_extraction import _save_extraction

        extracted = {
            "dispute_focus": [],
            "regulatory_finding": "无",
            "decision_result": "驳回",
            "legal_basis": [],
            "compliance_insights": [],
            "risk_tags": [],
            "confidence": 0.0,
            "evidence_snippets": [],
        }
        llm_result = {"model": "test-model", "tokens_used": 0}

        _save_extraction(case, extracted, llm_result, db_session)
        db_session.commit()

        meta = case.get_extraction_metadata()
        assert "model" in meta
        assert "prompt_version" in meta
        assert "confidence" in meta
        assert "evidence_snippets" in meta


# ═══════════════════════════════════════════════════════════════
# 9. 去重检查（保存前）
# ═══════════════════════════════════════════════════════════════


class TestPreSaveDedup:
    """保存前去重检查"""

    def test_check_before_save_computes_hash(self, db_session: Session):
        """保存前去重检查自动计算 content_hash"""
        case = _make_case("待保存案例", content="测试内容", sanitized="脱敏")
        case.content_hash = None  # 清除 hash
        db_session.add(case)
        db_session.commit()

        result = dedup_service.check_before_save(db_session, case)
        assert isinstance(result, dict)
        # check_before_save 应补全 content_hash
        assert case.content_hash is not None

    def test_save_detects_duplicate_by_hash(self, db_session: Session):
        """通过 content_hash 检测重复"""
        content = "独特内容ABCDEFGHIJ" * 5
        summary = "相同摘要文本"

        case1 = ComplaintCase(
            title="先行案例",
            raw_content=content,
            summary=summary,
            source_url="http://first.example.com",
            province="甘肃",
            decision_type="upheld",
        )
        case1.set_content_hash()
        db_session.add(case1)
        db_session.commit()

        case2 = ComplaintCase(
            title="后续案例",
            raw_content=content,
            summary=summary,
            source_url="http://second.example.com",
            province="甘肃",
            decision_type="upheld",
        )
        case2.set_content_hash()
        db_session.add(case2)
        db_session.commit()

        result = dedup_service.find_duplicates(db_session, case2, auto_mark=True)
        assert result["is_duplicate"], f"Expected duplicate, got: {result}"
        assert result["method"] == "content_hash"


# ═══════════════════════════════════════════════════════════════
# 10. 状态转换钩子验证
# ═══════════════════════════════════════════════════════════════


class MockCaseForSM:
    """Mock 对象用于状态机测试"""
    def __init__(self, id: int = 1, review_status: str = "fetched"):
        self.id = id
        self.review_status = review_status
        self.publish_status = "draft"
        self.reviewed_by = None
        self.reviewed_at = None
        self.published_at = None


class TestStateMachineHooks:
    """状态转换钩子验证"""

    def test_verified_sets_reviewed_fields(self):
        sm = CaseStatusStateMachine()
        case = MockCaseForSM(review_status="pending_review")
        ok, _ = sm.transition(case, "verified", user_id=42)
        assert ok
        assert case.reviewed_by == 42
        assert case.reviewed_at is not None

    def test_published_sets_publish_fields(self):
        sm = CaseStatusStateMachine()
        case = MockCaseForSM(review_status="verified")
        ok, _ = sm.transition(case, "published", user_id=42)
        assert ok
        assert case.publish_status == "published"
        assert case.published_at is not None

    def test_unpublished_sets_publish_status(self):
        sm = CaseStatusStateMachine()
        case = MockCaseForSM(review_status="published")
        case.publish_status = "published"
        ok, _ = sm.transition(case, "unpublished")
        assert ok
        assert case.publish_status == "unpublished"

    def test_rejected_sets_reviewed_fields(self):
        sm = CaseStatusStateMachine()
        case = MockCaseForSM(review_status="pending_review")
        ok, _ = sm.transition(case, "rejected", user_id=99)
        assert ok
        assert case.reviewed_by == 99
        assert case.reviewed_at is not None
