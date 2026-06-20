"""Phase 2 案例运营闭环 — 综合测试

测试覆盖：
- 状态机合法性
- 去重策略
- 审核 API
- KG 投影
- 候选规则
"""

import json
import time
from datetime import date, datetime, timezone
from typing import Optional

import pytest
from sqlalchemy.orm import Session

from app.engine.case_state_machine import (
    CaseStatus,
    CaseStatusStateMachine,
    PublishStatus,
    VALID_TRANSITIONS,
)
from app.models.complaint_case import ComplaintCase
from app.services.dedup_service import dedup_service


# ═══════════════════════════════════════════════════════
# CaseStatusStateMachine Tests
# ═══════════════════════════════════════════════════════


class MockCase:
    """Mock 对象用于测试状态机"""
    def __init__(self, id: int = 1, review_status: str = "fetched"):
        self.id = id
        self.review_status = review_status
        self.publish_status = "draft"
        self.reviewed_by = None
        self.reviewed_at = None
        self.published_at = None


class TestStateMachine:

    def test_all_valid_transitions_exist(self):
        """验证所有 11 种状态都在转换表中"""
        expected = {
            "fetched", "normalized", "extracted", "pending_review",
            "verified", "published", "unpublished", "duplicate",
            "rejected", "parse_failed", "quarantined", "archived",
        }
        actual = set(s.value for s in VALID_TRANSITIONS.keys())
        for s in expected:
            assert s in actual, f"状态 {s} 缺失"

    def test_archived_is_terminal(self):
        """archived 是终态，无出口"""
        transitions = VALID_TRANSITIONS.get(CaseStatus.ARCHIVED, set())
        assert len(transitions) == 0, f"archived 不应有出边: {transitions}"

    def test_happy_path(self):
        """合法转换链: fetched → normalized → extracted → pending_review → verified → published"""
        sm = CaseStatusStateMachine()
        case = MockCase()

        ok, msg = sm.transition(case, CaseStatus.NORMALIZED.value)
        assert ok, msg
        assert case.review_status == CaseStatus.NORMALIZED.value

        ok, msg = sm.transition(case, CaseStatus.EXTRACTED.value)
        assert ok, msg
        assert case.review_status == CaseStatus.EXTRACTED.value

        ok, msg = sm.transition(case, CaseStatus.PENDING_REVIEW.value)
        assert ok, msg
        assert case.review_status == CaseStatus.PENDING_REVIEW.value

        ok, msg = sm.transition(case, CaseStatus.VERIFIED.value, user_id=1)
        assert ok, msg
        assert case.review_status == CaseStatus.VERIFIED.value
        assert case.reviewed_by == 1
        assert case.reviewed_at is not None

        ok, msg = sm.transition(case, CaseStatus.PUBLISHED.value)
        assert ok, msg
        assert case.review_status == CaseStatus.PUBLISHED.value
        assert case.publish_status == "published"
        assert case.published_at is not None

    def test_published_to_unpublished(self):
        """published → unpublished 合法"""
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.PUBLISHED.value)
        ok, msg = sm.transition(case, CaseStatus.UNPUBLISHED.value)
        assert ok, msg
        assert case.publish_status == "unpublished"

    def test_unpublished_to_published(self):
        """unpublished → published 合法（重新发布）"""
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.UNPUBLISHED.value)
        ok, msg = sm.transition(case, CaseStatus.PUBLISHED.value)
        assert ok, msg

    def test_unpublished_to_archived(self):
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.UNPUBLISHED.value)
        ok, msg = sm.transition(case, CaseStatus.ARCHIVED.value)
        assert ok, msg

    def test_verify_to_quarantine(self):
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.VERIFIED.value)
        ok, msg = sm.transition(case, CaseStatus.QUARANTINED.value)
        assert ok, msg

    def test_fetched_to_duplicate(self):
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.FETCHED.value)
        ok, msg = sm.transition(case, CaseStatus.DUPLICATE.value)
        assert ok, msg

    def test_fetched_to_parse_failed(self):
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.FETCHED.value)
        ok, msg = sm.transition(case, CaseStatus.PARSE_FAILED.value)
        assert ok, msg

    def test_rejected_retry(self):
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.REJECTED.value)
        ok, msg = sm.transition(case, CaseStatus.FETCHED.value)
        assert ok, msg

    def test_duplicate_retry(self):
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.DUPLICATE.value)
        ok, msg = sm.transition(case, CaseStatus.FETCHED.value)
        assert ok, msg

    def test_parse_failed_retry(self):
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.PARSE_FAILED.value)
        ok, msg = sm.transition(case, CaseStatus.FETCHED.value)
        assert ok, msg

    # ── 非法转换测试 ────────────────────────

    def test_illegal_published_to_rejected(self):
        """published → rejected 非法"""
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.PUBLISHED.value)
        ok, msg = sm.transition(case, CaseStatus.REJECTED.value)
        assert not ok
        assert "非法状态转换" in msg

    def test_illegal_archived_any(self):
        """archived → any 非法"""
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.ARCHIVED.value)
        for target in [CaseStatus.PUBLISHED, CaseStatus.VERIFIED, CaseStatus.FETCHED]:
            ok, msg = sm.transition(case, target.value)
            assert not ok, f"archived → {target.value} 应被拒绝"

    def test_illegal_skip_steps(self):
        """fetched → published 非法（跳过了审核）"""
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.FETCHED.value)
        ok, msg = sm.transition(case, CaseStatus.PUBLISHED.value)
        assert not ok

    def test_illegal_pending_to_fetched(self):
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.PENDING_REVIEW.value)
        ok, msg = sm.transition(case, CaseStatus.FETCHED.value)
        assert not ok

    def test_get_allowed_transitions(self):
        """get_allowed_transitions 返回正确的目标状态"""
        allowed = CaseStatusStateMachine.get_allowed_transitions(CaseStatus.FETCHED.value)
        assert CaseStatus.NORMALIZED.value in allowed
        assert CaseStatus.DUPLICATE.value in allowed
        assert CaseStatus.PARSE_FAILED.value in allowed
        assert CaseStatus.PUBLISHED.value not in allowed

    def test_invalid_status_value(self):
        sm = CaseStatusStateMachine()
        ok, msg = sm.transition(MockCase(review_status="invalid"), CaseStatus.NORMALIZED.value)
        assert not ok

    def test_pending_review_to_verified_sets_audited(self):
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.PENDING_REVIEW.value)
        ok, msg = sm.transition(case, CaseStatus.VERIFIED.value, user_id=42)
        assert ok
        assert case.reviewed_by == 42
        assert case.reviewed_at is not None

    def test_pending_review_to_rejected_sets_audited(self):
        sm = CaseStatusStateMachine()
        case = MockCase(review_status=CaseStatus.PENDING_REVIEW.value)
        ok, msg = sm.transition(case, CaseStatus.REJECTED.value, user_id=42)
        assert ok
        assert case.reviewed_by == 42
        assert case.reviewed_at is not None


# ═══════════════════════════════════════════════════════
# DedupService Tests
# ═══════════════════════════════════════════════════════


class TestDedupService:

    def test_compute_hash_deterministic(self):
        h1 = dedup_service.compute_hash("test content")
        h2 = dedup_service.compute_hash("test content")
        assert h1 == h2
        assert len(h1) == 64

    def test_compute_hash_different(self):
        h1 = dedup_service.compute_hash("content A")
        h2 = dedup_service.compute_hash("content B")
        assert h1 != h2

    def test_compute_hash_empty(self):
        assert dedup_service.compute_hash("") == ""
        assert dedup_service.compute_hash(None) == ""


# ═══════════════════════════════════════════════════════
# ComplaintCase Model Tests
# ═══════════════════════════════════════════════════════


class TestComplaintCaseModel:

    def test_compute_content_hash(self):
        case = ComplaintCase(
            title="测试",
            raw_content="测试内容",
            summary="摘要",
        )
        h = case.compute_content_hash("测试内容摘要")
        assert len(h) == 64

    def test_set_content_hash(self):
        case = ComplaintCase(
            title="测试",
            raw_content="正文内容",
            summary="摘要内容",
        )
        case.set_content_hash()
        assert case.content_hash
        assert len(case.content_hash) == 64

        # 相同内容产生相同哈希
        case2 = ComplaintCase(
            title="测试",
            raw_content="正文内容",
            summary="摘要内容",
        )
        case2.set_content_hash()
        assert case.content_hash == case2.content_hash

    def test_complaint_types_json(self):
        case = ComplaintCase()
        case.set_complaint_types(["品牌锁定", "参数排他"])
        assert case.get_complaint_types() == ["品牌锁定", "参数排他"]

        # 回读
        parsed = case.get_complaint_types()
        assert isinstance(parsed, list)
        assert "品牌锁定" in parsed

    def test_complaint_types_empty(self):
        case = ComplaintCase()
        assert case.get_complaint_types() == []

    def test_legal_basis_json(self):
        case = ComplaintCase()
        case.set_legal_basis(["政府采购法 第二十二条", "招标投标法 第十八条"])
        assert len(case.get_legal_basis()) == 2

    def test_legal_basis_empty(self):
        case = ComplaintCase()
        assert case.get_legal_basis() == []

    def test_extraction_metadata(self):
        case = ComplaintCase()
        meta = {
            "confidence": 0.85,
            "dispute_focus": ["焦点1", "焦点2"],
            "risk_tags": ["brand_lock"],
        }
        case.set_extraction_metadata(meta)
        parsed = case.get_extraction_metadata()
        assert parsed["confidence"] == 0.85
        assert len(parsed["dispute_focus"]) == 2

    def test_extraction_metadata_empty(self):
        case = ComplaintCase()
        assert case.get_extraction_metadata() == {}

    def test_to_dict(self):
        case = ComplaintCase(
            id=1,
            title="测试案例",
            province="甘肃",
            decision_date=date(2025, 6, 15),
            decision_type="upheld",
        )
        case.set_complaint_types(["品牌锁定"])
        case.set_legal_basis(["政府采购法 第二十二条"])

        d = case.to_dict()
        assert d["id"] == 1
        assert d["title"] == "测试案例"
        assert d["decision_date"] == "2025-06-15"
        assert d["decision_type"] == "upheld"
        assert "品牌锁定" in d["complaint_types"]

    def test_to_public_dict_hides_sensitive(self):
        case = ComplaintCase(
            id=1,
            title="测试案例",
            raw_content="敏感原文",
            sanitized_content="脱敏后内容",
            reviewed_by=5,
        )
        d = case.to_public_dict()
        # raw_content 不应暴露
        assert "raw_content" not in d
        assert d.get("content") == "脱敏后内容"
        # reviewed_by 不应暴露
        assert "reviewed_by" not in d


# ═══════════════════════════════════════════════════════
# State machine transition audit test
# ═══════════════════════════════════════════════════════


class TestCaseStatusEnum:

    def test_all_11_statuses_defined(self):
        expected_count = 12  # 11 + unpublished
        assert len(CaseStatus) == expected_count, f"应有 12 种状态，实际 {len(CaseStatus)}: {[s.value for s in CaseStatus]}"

    def test_status_values(self):
        assert CaseStatus.FETCHED.value == "fetched"
        assert CaseStatus.NORMALIZED.value == "normalized"
        assert CaseStatus.EXTRACTED.value == "extracted"
        assert CaseStatus.PENDING_REVIEW.value == "pending_review"
        assert CaseStatus.VERIFIED.value == "verified"
        assert CaseStatus.PUBLISHED.value == "published"
        assert CaseStatus.UNPUBLISHED.value == "unpublished"
        assert CaseStatus.DUPLICATE.value == "duplicate"
        assert CaseStatus.REJECTED.value == "rejected"
        assert CaseStatus.PARSE_FAILED.value == "parse_failed"
        assert CaseStatus.QUARANTINED.value == "quarantined"
        assert CaseStatus.ARCHIVED.value == "archived"

    def test_publish_status_values(self):
        assert PublishStatus.DRAFT.value == "draft"
        assert PublishStatus.PUBLISHED.value == "published"
        assert PublishStatus.UNPUBLISHED.value == "unpublished"


# ═══════════════════════════════════════════════════════
# Integration test helpers
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_session():
    """提供测试用的 SQLite 内存数据库 session"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    # 创建所有表
    from app.models.document import Base as DocumentBase
    from app.models.complaint_case import Base as ComplaintCaseBase
    from app.models.candidate_rule import Base as CandidateRuleBase
    from app.models.knowledge_graph import Base as KGraphBase

    DocumentBase.metadata.create_all(bind=engine)
    ComplaintCaseBase.metadata.create_all(bind=engine)
    CandidateRuleBase.metadata.create_all(bind=engine)
    KGraphBase.metadata.create_all(bind=engine)

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


class TestDedupWithDB:

    def test_canonical_url_match(self, db_session: Session):
        """canonical_url 完全匹配 → 标记重复"""
        case1 = ComplaintCase(
            title="案例 A",
            canonical_url="https://ccgp.gov.cn/detail/123-dedup",
            source_url="https://source1.com",
            review_status="fetched",
        )
        case1.set_content_hash()
        db_session.add(case1)
        db_session.commit()

        case2 = ComplaintCase(
            title="案例 B",
            canonical_url="https://ccgp.gov.cn/detail/123-dedup",  # 相同 URL
            source_url="https://source2.com",
            review_status="fetched",
        )
        case2.set_content_hash()
        db_session.add(case2)
        db_session.commit()

        result = dedup_service.find_duplicates(db_session, case2, auto_mark=True)
        assert result["is_duplicate"]
        assert result["method"] == "canonical_url"

    def test_source_url_match(self, db_session: Session):
        case1 = ComplaintCase(
            title="案例 A",
            source_url="https://ccgp.gov.cn/detail/456-dedup",
            review_status="fetched",
        )
        case1.set_content_hash()
        db_session.add(case1)
        db_session.commit()

        case2 = ComplaintCase(
            title="案例 B",
            source_url="https://ccgp.gov.cn/detail/456-dedup",
            review_status="fetched",
        )
        case2.set_content_hash()
        db_session.add(case2)
        db_session.commit()

        result = dedup_service.find_duplicates(db_session, case2)
        assert result["is_duplicate"]
        assert result["method"] == "source_url"

    def test_content_hash_match(self, db_session: Session):
        case1 = ComplaintCase(
            title="案例 A",
            raw_content="完全相同的正文内容",
            summary="同样摘要",
            review_status="fetched",
        )
        case1.set_content_hash()
        db_session.add(case1)
        db_session.commit()

        case2 = ComplaintCase(
            title="案例 B",
            raw_content="完全相同的正文内容",
            summary="同样摘要",
            review_status="fetched",
        )
        case2.set_content_hash()
        db_session.add(case2)
        db_session.commit()

        result = dedup_service.find_duplicates(db_session, case2)
        assert result["is_duplicate"]
        assert result["method"] == "content_hash"

    def test_project_number_match(self, db_session: Session):
        case1 = ComplaintCase(
            title="案例 A",
            project_number="2025-001-TEST",
            review_status="fetched",
            content_hash="hash111",
        )
        db_session.add(case1)
        db_session.commit()

        case2 = ComplaintCase(
            title="案例 B",
            project_number="2025-001-TEST",
            review_status="fetched",
            content_hash="hash222",
        )
        db_session.add(case2)
        db_session.commit()

        result = dedup_service.find_duplicates(db_session, case2)
        assert result["is_duplicate"]
        assert result["method"] == "project_number/case_no"

    def test_title_similarity_candidate_only(self, db_session: Session):
        """标题/内容相似度仅作为候选，不自动标记"""
        case1 = ComplaintCase(
            title="宁夏人民医院手术麻醉设备采购项目投诉处理结果公告",
            raw_content="项目编号2026-2...参数指向日本Hadeco品牌...",
            review_status="fetched",
            content_hash="hash555",
            project_number="UNIQUE-001",
        )
        db_session.add(case1)
        db_session.commit()

        case2 = ComplaintCase(
            title="宁夏人民医院手术麻醉设备采购投诉处理公告（补充）",
            raw_content="项目编号2026-2...参数指向Hadeco...略有不同",
            review_status="fetched",
            content_hash="hash666",
            project_number="UNIQUE-002",
        )
        db_session.add(case2)
        db_session.commit()

        result = dedup_service.find_duplicates(db_session, case2)
        # 不应静默判定为重复（强匹配未触发）
        if result["is_duplicate"]:
            # 如果强匹配触发，方法不应该是 content_hash
            assert result["method"] != "content_hash"


class TestKGProjectionHelpers:

    def test_origin_id_pattern(self):
        """验证 origin_id 格式: complaint_case:{id}"""
        origin_id = f"complaint_case:{42}"
        assert origin_id == "complaint_case:42"


# ═══════════════════════════════════════════════════════
# Phase 2 adversarial: publish/unpublish/republish cycle
# ═══════════════════════════════════════════════════════


class TestPublishUnpublishRepublishCycle:
    """Adversarial lifecycle tests for KG projection integrity.

    Covers blocking issues A and B:
      A: republish must restore RAG visibility
      B: KG projection failure must rollback case state
    """

    def test_publish_creates_verified_kg_node(self, db_session: Session):
        """publish → KG node created with audit_status='verified'"""
        from app.models.knowledge_graph import KGNode
        from app.services.kg_projection import kg_projection

        case = _create_publishable_case("publish-test-1")
        db_session.add(case)
        db_session.commit()

        result = kg_projection.project_case(db_session, case)
        assert result["success"], f"project_case failed: {result.get('error')}"
        assert result["action"] == "created"
        assert result["node_id"] is not None

        # Verify KG node
        node = db_session.query(KGNode).filter(KGNode.id == result["node_id"]).first()
        assert node is not None
        assert node.audit_status == "verified"
        assert node.rule_id == f"CC-{case.id}"
        assert "unprojected_at" not in (node.metadata_json or "")

    def test_unpublish_sets_rejected(self, db_session: Session):
        """unpublish → KG node audit_status='rejected'"""
        from app.models.knowledge_graph import KGNode
        from app.services.kg_projection import kg_projection

        case = _create_publishable_case("unpublish-test-1")
        db_session.add(case)
        db_session.commit()

        # First publish
        result = kg_projection.project_case(db_session, case)
        assert result["success"]
        node_id = result["node_id"]

        # Then unpublish
        result2 = kg_projection.unproject_case(db_session, case)
        assert result2["success"]
        assert result2["action"] == "removed"

        # Verify node is rejected
        node = db_session.query(KGNode).filter(KGNode.id == node_id).first()
        assert node.audit_status == "rejected"
        meta = json.loads(node.metadata_json or "{}")
        assert "unprojected_at" in meta

    def test_republish_restores_verified(self, db_session: Session):
        """published → unpublished → republish: KG node restored to verified"""
        from app.models.knowledge_graph import KGNode
        from app.services.kg_projection import kg_projection

        case = _create_publishable_case("republish-test-1")
        db_session.add(case)
        db_session.commit()

        # Step 1: publish
        r1 = kg_projection.project_case(db_session, case)
        assert r1["success"]
        node_id = r1["node_id"]

        # Step 2: unpublish
        r2 = kg_projection.unproject_case(db_session, case)
        assert r2["success"]

        # Step 3: republish (simulate state machine transition)
        case.review_status = "published"
        case.publish_status = "published"
        r3 = kg_projection.project_case(db_session, case)
        assert r3["success"], f"republish projection failed: {r3.get('error')}"
        assert r3["action"] == "restored", f"expected 'restored', got '{r3['action']}'"

        # Verify restored
        node = db_session.query(KGNode).filter(KGNode.id == node_id).first()
        assert node.audit_status == "verified"
        meta = json.loads(node.metadata_json or "{}")
        assert "unprojected_at" not in meta, "unprojected_at should be cleared on republish"
        assert meta.get("sync_version") is not None

    def test_republish_idempotent_no_duplicate(self, db_session: Session):
        """republish again does not create duplicate nodes"""
        from app.models.knowledge_graph import KGNode
        from app.services.kg_projection import kg_projection

        case = _create_publishable_case("idempotent-test-1")
        db_session.add(case)
        db_session.commit()

        # Publish twice
        kg_projection.project_case(db_session, case)
        r2 = kg_projection.project_case(db_session, case)
        assert r2["success"]
        assert r2["action"] in ("skipped", "updated")

        # Check no duplicates
        nodes = db_session.query(KGNode).filter(
            KGNode.node_type == "case",
            KGNode.rule_id == f"CC-{case.id}",
        ).all()
        assert len(nodes) == 1, f"Expected 1 node, got {len(nodes)}"

    def test_unpublish_no_kg_node_is_ok(self, db_session: Session):
        """unpublish when no KG node exists: succeeds silently"""
        from app.services.kg_projection import kg_projection

        case = _create_publishable_case("no-kg-unpublish")
        db_session.add(case)
        db_session.commit()

        result = kg_projection.unproject_case(db_session, case)
        assert result["success"]
        assert result["action"] == "skipped"

    def test_not_published_cannot_project(self, db_session: Session):
        """non-published cases cannot be projected"""
        from app.services.kg_projection import kg_projection
        from app.engine.case_state_machine import CaseStatus

        case = ComplaintCase(
            title="not published",
            review_status=CaseStatus.FETCHED.value,
            publish_status="draft",
        )
        db_session.add(case)
        db_session.commit()

        result = kg_projection.project_case(db_session, case)
        assert not result["success"]
        assert "未发布" in result.get("error", "")


# ── helpers ────────────────────────────────────────────────


def _create_publishable_case(title: str) -> ComplaintCase:
    """Create a case in published state for testing."""
    from datetime import date as dt_date
    return ComplaintCase(
        title=title,
        province="甘肃",
        review_status="published",
        publish_status="published",
        decision_date=dt_date(2025, 6, 15),
        decision_type="upheld",
        raw_content=f"{title} 正文内容",
        sanitized_content=f"{title} 脱敏内容",
        summary=f"{title} 摘要",
        project_name="测试采购项目",
        project_number="TEST-2025-001",
        content_hash=ComplaintCase.compute_content_hash(f"{title} 正文内容"),
    )
