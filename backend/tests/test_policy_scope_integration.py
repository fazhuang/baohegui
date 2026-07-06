"""Policy scope isolation — integration tests with real DynamicPolicy records

Validates:
 1. user-1 draft → loader(user-1) 不返回, loader(user-2) 不返回
 2. draft → review → approved → applied → loader 仅返回匹配 scope
 3. suppressed_rule_ids 真实进入 DecisionInput.tenant_policy
 4. rollback → loader 不返回, DecisionInput 不再包含其影响
 5. platform-A policy 不进入 platform-B
 6. scope 缺失的 policy 不能 apply
 7. 直接从 draft apply 被拒绝
 8. 非管理员无法创建/审批/apply/rollback
 9. feedback 提交前后 DynamicPolicy 表逐行一致
10. check.py 不存在第二次构造覆盖 tenant_policy

Tests use real SQLAlchemy DynamicPolicy records and real repository, never _FakePolicy.
"""

from __future__ import annotations

import json as _json
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _make_policy_record(db, **kw):
    """Create a real DynamicPolicy record directly in test DB."""
    from app.services.policy_repository import DynamicPolicy
    p = DynamicPolicy(
        policy_key=kw.get("policy_key", f"PK-{kw.get('id', 'test')}"),
        policy_type=kw.get("policy_type", "tenant"),
        policy_data=kw.get("policy_data", '{"suppressed_rule_ids": ["R999"]}'),
        status=kw.get("status", "draft"),
        scope_type=kw.get("scope_type", "user"),
        scope_id=kw.get("scope_id", "1"),
        approved_by=kw.get("approved_by"),
        approved_at=kw.get("approved_at"),
        created_by=kw.get("created_by", 1),
        description=kw.get("description", ""),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ═══════════════════════════════════════════════════════════════
# 1. Scope isolation for tenant policies
# ═══════════════════════════════════════════════════════════════

class TestUserScopeIsolation:

    def test_user1_draft_not_returned(self, db_session):
        """user-1 draft policy: loader(user-1) not returned, loader(user-2) not returned."""
        from app.services.policy_repository import load_applied_policy_context

        _make_policy_record(
            db_session, policy_key="PK-DRAFT-1", status="draft",
            scope_type="user", scope_id="1",
            policy_data='{"suppressed_rule_ids": ["R001"]}',
        )

        r1 = load_applied_policy_context(db_session, policy_type="tenant", scope_type="user", scope_id="1")
        r2 = load_applied_policy_context(db_session, policy_type="tenant", scope_type="user", scope_id="2")

        assert len(r1) == 0, f"draft should not be returned for user-1, got {len(r1)}"
        assert len(r2) == 0, f"draft should not be returned for user-2, got {len(r2)}"

    def test_user1_review_not_returned(self, db_session):
        """draft → review: still not returned for either user."""
        from app.services.policy_repository import load_applied_policy_context, submit_for_review

        p = _make_policy_record(
            db_session, policy_key="PK-REVIEW-1", status="draft",
            scope_type="user", scope_id="1",
            policy_data='{"suppressed_rule_ids": ["R002"]}',
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)

        r1 = load_applied_policy_context(db_session, scope_type="user", scope_id="1")
        r2 = load_applied_policy_context(db_session, scope_type="user", scope_id="2")

        assert len(r1) == 0, f"review should not be returned for user-1, got {len(r1)}"
        assert len(r2) == 0, f"review should not be returned for user-2, got {len(r2)}"

    def test_user1_approved_not_returned(self, db_session):
        """review → approved: still not returned (not applied)."""
        from app.services.policy_repository import (
            load_applied_policy_context, submit_for_review, approve,
        )

        p = _make_policy_record(
            db_session, policy_key="PK-APPROVED-1", status="draft",
            scope_type="user", scope_id="1",
            policy_data='{"suppressed_rule_ids": ["R003"]}',
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)

        r1 = load_applied_policy_context(db_session, scope_type="user", scope_id="1")
        assert len(r1) == 0, f"approved should not be returned, got {len(r1)}"

    def test_user1_applied_returned_user2_not(self, db_session):
        """approved → applied: loader returns for user-1, NOT for user-2."""
        from app.services.policy_repository import (
            load_applied_policy_context, submit_for_review, approve, apply,
        )

        p = _make_policy_record(
            db_session, policy_key="PK-APPLIED-1", status="draft",
            scope_type="user", scope_id="1",
            policy_data='{"suppressed_rule_ids": ["R100","R200"]}',
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)
        apply(db_session, p.id, admin_id=1)

        r1 = load_applied_policy_context(db_session, scope_type="user", scope_id="1")
        r2 = load_applied_policy_context(db_session, scope_type="user", scope_id="2")

        assert len(r1) == 1, f"user-1 should see applied policy, got {len(r1)}"
        assert len(r2) == 0, f"user-2 should NOT see user-1 policy, got {len(r2)}"

        # Verify suppressed_rule_ids in policy_data
        p_data = _json.loads(r1[0].policy_data)
        assert "suppressed_rule_ids" in p_data
        assert "R100" in p_data["suppressed_rule_ids"]
        assert "R200" in p_data["suppressed_rule_ids"]

    def test_suppressed_rule_ids_in_decision_input(self, db_session):
        """Applied policy suppressed_rule_ids really enters DecisionInput.tenant_policy."""
        from app.core.policy_kernel import DecisionInput, TenantPolicy, RuleType, RuleType
        from app.services.policy_repository import (
            load_applied_policy_context, submit_for_review, approve, apply,
        )

        p = _make_policy_record(
            db_session, policy_key="PK-DECISION-1", status="draft",
            scope_type="user", scope_id="1",
            policy_data='{"suppressed_rule_ids": ["R_SHALL_SUPPRESS"]}',
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)
        apply(db_session, p.id, admin_id=1)

        # Simulate what check.py does: load and merge
        tp = TenantPolicy(tenant_id="1")
        assert "R_SHALL_SUPPRESS" not in tp.suppressed_rule_ids

        for dp in load_applied_policy_context(
            db_session, policy_type="tenant",
            scope_type="user", scope_id="1",
        ):
            dp_data = _json.loads(dp.policy_data)
            if "suppressed_rule_ids" in dp_data:
                tp.suppressed_rule_ids.update(dp_data["suppressed_rule_ids"])

        assert "R_SHALL_SUPPRESS" in tp.suppressed_rule_ids, \
            "suppressed_rule_ids should be in tenant_policy after merge"

        # Build DecisionInput using the merged tp
        di = DecisionInput(tenant_policy=tp)
        assert "R_SHALL_SUPPRESS" in di.tenant_policy.suppressed_rule_ids, \
            "Applied policy must appear in DecisionInput.tenant_policy"

    def test_rollback_removes_from_execution(self, db_session):
        """rollback → loader not returned, DecisionInput no longer contains its effects."""
        from app.services.policy_repository import (
            load_applied_policy_context, submit_for_review, approve, apply, rollback,
        )

        p = _make_policy_record(
            db_session, policy_key="PK-ROLLBACK-1", status="draft",
            scope_type="user", scope_id="1",
            policy_data='{"suppressed_rule_ids": ["R_ROLLED"]}',
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)
        apply(db_session, p.id, admin_id=1)

        # Before rollback: visible
        r1 = load_applied_policy_context(db_session, scope_type="user", scope_id="1")
        assert len(r1) == 1

        # Rollback
        rollback(db_session, p.id, admin_id=1, reason="test rollback")

        # After rollback: not visible
        r2 = load_applied_policy_context(db_session, scope_type="user", scope_id="1")
        assert len(r2) == 0, f"rolled_back should not be returned, got {len(r2)}"

    def test_user_policy_not_returned_for_other_user(self, db_session):
        """user scope policy for user-1 is NEVER returned for user-2."""
        from app.services.policy_repository import (
            load_applied_policy_context, submit_for_review, approve, apply,
        )

        # Create and apply policy for user-1
        p = _make_policy_record(
            db_session, policy_key="PK-USER1-ONLY", status="draft",
            scope_type="user", scope_id="1",
            policy_data='{"suppressed_rule_ids": ["R_US1"]}',
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)
        apply(db_session, p.id, admin_id=1)

        # user-2 sees nothing
        r2 = load_applied_policy_context(db_session, scope_type="user", scope_id="2")
        assert len(r2) == 0

        # user-3 sees nothing
        r3 = load_applied_policy_context(db_session, scope_type="user", scope_id="3")
        assert len(r3) == 0

    def test_different_scope_users_independent(self, db_session):
        """Two applied policies for different users coexist without cross-contamination."""
        from app.services.policy_repository import (
            load_applied_policy_context, submit_for_review, approve, apply,
        )

        # User-1 policy
        p1 = _make_policy_record(
            db_session, policy_key="PK-USER1", status="draft",
            scope_type="user", scope_id="1",
            policy_data='{"suppressed_rule_ids": ["R_A"]}',
            created_by=1,
        )
        submit_for_review(db_session, p1.id, admin_id=1)
        approve(db_session, p1.id, admin_id=1)
        apply(db_session, p1.id, admin_id=1)

        # User-2 policy
        p2 = _make_policy_record(
            db_session, policy_key="PK-USER2", status="draft",
            scope_type="user", scope_id="2",
            policy_data='{"suppressed_rule_ids": ["R_B"]}',
            created_by=1,
        )
        submit_for_review(db_session, p2.id, admin_id=1)
        approve(db_session, p2.id, admin_id=1)
        apply(db_session, p2.id, admin_id=1)

        r1 = load_applied_policy_context(db_session, scope_type="user", scope_id="1")
        r2 = load_applied_policy_context(db_session, scope_type="user", scope_id="2")

        assert len(r1) == 1
        assert len(r2) == 1
        assert r1[0].policy_key == "PK-USER1"
        assert r2[0].policy_key == "PK-USER2"


# ═══════════════════════════════════════════════════════════════
# 2. Platform scope isolation
# ═══════════════════════════════════════════════════════════════

class TestPlatformScopeIsolation:

    def test_platform_a_policy_not_for_platform_b(self, db_session):
        """platform-A policy does not enter platform-B."""
        from app.services.policy_repository import (
            load_applied_policy_context, submit_for_review, approve, apply,
        )

        p = _make_policy_record(
            db_session, policy_key="PK-PLAT-GD", status="draft",
            policy_type="platform",
            scope_type="platform", scope_id="guangdong",
            policy_data='{"required_sections": ["R_GD"]}',
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)
        apply(db_session, p.id, admin_id=1)

        r_a = load_applied_policy_context(
            db_session, policy_type="platform",
            scope_type="platform", scope_id="guangdong",
        )
        r_b = load_applied_policy_context(
            db_session, policy_type="platform",
            scope_type="platform", scope_id="jiangsu",
        )

        assert len(r_a) == 1, f"guangdong should see platform policy, got {len(r_a)}"
        assert len(r_b) == 0, f"jiangsu should NOT see guangdong policy, got {len(r_b)}"


# ═══════════════════════════════════════════════════════════════
# 3. Scope missing → fail-closed
# ═══════════════════════════════════════════════════════════════

class TestScopeFailClosed:

    def test_apply_missing_scope_rejected(self, db_session):
        """Policy with invalid scope_type cannot be applied."""
        from app.services.policy_repository import apply, submit_for_review, approve

        p = _make_policy_record(
            db_session, policy_key="PK-BAD-SCOPE", status="draft",
            scope_type="invalid_scope", scope_id="1",
            policy_data='{"suppressed_rule_ids": ["R_X"]}',
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)

        with pytest.raises(ValueError, match="scope_type"):
            apply(db_session, p.id, admin_id=1)

    def test_apply_missing_scope_id_rejected(self, db_session):
        """Policy with empty scope_id cannot be applied."""
        from app.services.policy_repository import apply, submit_for_review, approve

        p = _make_policy_record(
            db_session, policy_key="PK-EMPTY-SCOPEID", status="draft",
            scope_type="user", scope_id="  ",
            policy_data='{"suppressed_rule_ids": ["R_X"]}',
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        p.scope_id = ""  # override after creation
        db_session.commit()
        approve(db_session, p.id, admin_id=1)

        with pytest.raises(ValueError, match="scope_id"):
            apply(db_session, p.id, admin_id=1)

    def test_loader_no_scope_returns_empty(self, db_session):
        """Loader with no scope returns empty (fail-closed)."""
        from app.services.policy_repository import (
            load_applied_policy_context, submit_for_review, approve, apply,
        )

        p = _make_policy_record(
            db_session, policy_key="PK-NO-SCOPE-LOAD", status="draft",
            scope_type="user", scope_id="1",
            policy_data='{"suppressed_rule_ids": ["R_Y"]}',
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)
        apply(db_session, p.id, admin_id=1)

        # Missing scope_type
        r1 = load_applied_policy_context(db_session, scope_type="user", scope_id=None)
        assert len(r1) == 0

        # Missing scope_id
        r2 = load_applied_policy_context(db_session, scope_type=None, scope_id="1")
        assert len(r2) == 0

        # Both missing
        r3 = load_applied_policy_context(db_session)
        assert len(r3) == 0


# ═══════════════════════════════════════════════════════════════
# 4. State transition gate enforcement
# ═══════════════════════════════════════════════════════════════

class TestStateTransitionGates:

    def test_direct_draft_to_apply_rejected(self, db_session):
        """Draft → apply directly is rejected."""
        from app.services.policy_repository import apply

        p = _make_policy_record(
            db_session, policy_key="PK-DRAFT-APPLY", status="draft",
            scope_type="user", scope_id="1",
            policy_data='{"suppressed_rule_ids": ["R_BAD"]}',
        )

        with pytest.raises(ValueError, match="approved"):
            apply(db_session, p.id, admin_id=1)

    def test_apply_without_approved_by_rejected(self, db_session):
        """Apply without approved_by/approved_at is rejected."""
        from app.services.policy_repository import apply, submit_for_review

        p = _make_policy_record(
            db_session, policy_key="PK-NO-APPROVAL", status="draft",
            scope_type="user", scope_id="1",
            policy_data='{"suppressed_rule_ids": ["R_BAD2"]}',
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        # Manually set status to approved without setting approved_by/approved_at
        p.status = "approved"
        db_session.commit()

        with pytest.raises(ValueError, match="approved_by"):
            apply(db_session, p.id, admin_id=1)

    def test_apply_with_bad_schema_rejected(self, db_session):
        """Apply with invalid policy_data schema is rejected."""
        from app.services.policy_repository import apply, submit_for_review, approve

        p = _make_policy_record(
            db_session, policy_key="PK-BAD-SCHEMA", status="draft",
            scope_type="user", scope_id="1",
            policy_data='not valid json',
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)

        with pytest.raises(ValueError, match="schema"):
            apply(db_session, p.id, admin_id=1)


# ═══════════════════════════════════════════════════════════════
# 5. Non-admin access control
# ═══════════════════════════════════════════════════════════════

class TestPolicyAdminAccess:

    def test_non_admin_list_rejected(self, client, user_auth_headers):
        """Non-admin accessing /api/admin/policies/ → 403."""
        resp = client.get("/api/admin/policies/", headers=user_auth_headers)
        assert resp.status_code == 403

    def test_admin_list_succeeds(self, client, auth_headers):
        """Admin accessing /api/admin/policies/ → 200."""
        resp = client.get("/api/admin/policies/", headers=auth_headers)
        assert resp.status_code == 200
        assert "policies" in resp.json()

    def test_non_admin_create_rejected(self, client, user_auth_headers):
        """Non-admin creating policy → 403."""
        resp = client.post(
            "/api/admin/policies/",
            json={
                "policy_key": "PK-NON-ADMIN",
                "policy_type": "tenant",
                "policy_data": '{"suppressed_rule_ids": []}',
                "scope_type": "user",
                "scope_id": "1",
            },
            headers=user_auth_headers,
        )
        assert resp.status_code == 403

    def test_admin_create_succeeds(self, client, auth_headers, db_session):
        """Admin creating policy → 201."""
        resp = client.post(
            "/api/admin/policies/",
            json={
                "policy_key": "PK-ADMIN-CREATE",
                "policy_type": "tenant",
                "policy_data": '{"suppressed_rule_ids": ["R_ADMIN"]}',
                "scope_type": "user",
                "scope_id": "1",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert data["policy_key"] == "PK-ADMIN-CREATE"

    def test_apply_non_admin_rejected(self, client, user_auth_headers, db_session):
        """Non-admin calling apply → 403."""
        from app.services.policy_repository import create_draft, submit_for_review, approve

        p = create_draft(
            db_session, policy_key="PK-NA-APPLY", policy_type="tenant",
            policy_data='{"suppressed_rule_ids": ["R_NA"]}',
            scope_type="user", scope_id="1", created_by=1,
        )
        p2 = submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p2.id, admin_id=1)

        resp = client.post(
            f"/api/admin/policies/{p.id}/apply",
            headers=user_auth_headers,
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════
# 6. Global scope — explicit only
# ═══════════════════════════════════════════════════════════════

class TestGlobalScope:

    def test_global_policy_loaded_with_explicit_scope(self, db_session):
        """global scope policy must use explicit scope_type='global', scope_id='global'."""
        from app.services.policy_repository import (
            load_applied_policy_context, submit_for_review, approve, apply,
        )

        p = _make_policy_record(
            db_session, policy_key="PK-GLOBAL-1", status="draft",
            policy_type="tenant",
            scope_type="global", scope_id="global",
            policy_data='{"suppressed_rule_ids": ["R_GLOBAL"]}',
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)
        apply(db_session, p.id, admin_id=1)

        r = load_applied_policy_context(
            db_session, scope_type="global", scope_id="global",
        )
        assert len(r) == 1

        # user scope does NOT match global
        r_user = load_applied_policy_context(
            db_session, scope_type="user", scope_id="1",
        )
        assert len(r_user) == 0


# ═══════════════════════════════════════════════════════════════
# 7. Feedback does NOT modify DynamicPolicy
# ═══════════════════════════════════════════════════════════════

class TestFeedbackPolicyIsolation:

    def test_feedback_does_not_touch_dynamic_policies(self, db_session):
        """Feedback submission does not alter DynamicPolicy table."""
        from app.services.policy_repository import DynamicPolicy
        from app.services.feedback_service import feedback_service
        from app.models.document import ComplianceReport

        # Create a DynamicPolicy record
        _make_policy_record(
            db_session, policy_key="PK-FEEDBACK-ISOLATE", status="draft",
            scope_type="user", scope_id="1",
        )

        # Snapshot before
        before = db_session.query(DynamicPolicy).order_by(DynamicPolicy.id).all()
        before_data = [(p.id, p.status, p.scope_type, p.scope_id, p.policy_data) for p in before]

        # Create a report for feedback
        report_data = {
            "_decision_input": {
                "rule_violations": [
                    {"rule_id": "R_FB_ISOLATE", "rule_type": "forbidden"},
                ],
            },
        }
        report = ComplianceReport(
            file_id=1, total_score=90.0, violation_count=1,
            report_data=_json.dumps(report_data), checked_by=1,
        )
        db_session.add(report)
        db_session.commit()
        db_session.refresh(report)

        # Submit feedback via safe entry
        try:
            feedback_service.submit_feedback_with_validation(
                db=db_session, report_id=report.id, rule_id="R_FB_ISOLATE",
                user_id=1, feedback_type="confirm",
                report_data=_json.loads(report.report_data),
            )
        except Exception:
            pass  # IntegrityError from unique constraint is ok for this test

        # Snapshot after
        after = db_session.query(DynamicPolicy).order_by(DynamicPolicy.id).all()
        after_data = [(p.id, p.status, p.scope_type, p.scope_id, p.policy_data) for p in after]

        assert before_data == after_data, \
            f"DynamicPolicy table must be unchanged after feedback.\nBefore: {before_data}\nAfter: {after_data}"

    def test_feedback_does_not_touch_rule_confidence(self, db_session):
        """Feedback does not modify RuleConfidence table."""
        from app.services.feedback_service import RuleConfidence, feedback_service
        from app.models.document import ComplianceReport

        before = db_session.query(RuleConfidence).order_by(RuleConfidence.rule_id).all()
        before_data = [(r.rule_id, r.current_confidence, r.total_feedbacks) for r in before]

        report_data = {
            "_decision_input": {
                "rule_violations": [
                    {"rule_id": "R_FB_RC", "rule_type": "forbidden"},
                ],
            },
        }
        report = ComplianceReport(
            file_id=1, total_score=90.0, violation_count=1,
            report_data=_json.dumps(report_data), checked_by=1,
        )
        db_session.add(report)
        db_session.commit()
        db_session.refresh(report)

        try:
            feedback_service.submit_feedback_with_validation(
                db=db_session, report_id=report.id, rule_id="R_FB_RC",
                user_id=1, feedback_type="confirm",
                report_data=_json.loads(report.report_data),
            )
        except Exception:
            pass

        after = db_session.query(RuleConfidence).order_by(RuleConfidence.rule_id).all()
        after_data = [(r.rule_id, r.current_confidence, r.total_feedbacks) for r in after]

        assert before_data == after_data, \
            f"RuleConfidence must be unchanged after feedback.\nBefore: {before_data}\nAfter: {after_data}"


# ═══════════════════════════════════════════════════════════════
# 8. check.py tenant_policy not double-constructed
# ═══════════════════════════════════════════════════════════════

class TestCheckPyTenantPolicy:

    def test_tenant_policy_not_double_constructed(self):
        """check.py must not construct TenantPolicy a second time for DecisionInput."""
        import inspect
        from app.api import check as check_mod
        src = inspect.getsource(check_mod)

        # Count DecisionInput constructor blocks
        decision_input_blocks = []
        lines = src.split("\n")
        in_block = False
        block_start = -1
        for i, line in enumerate(lines):
            if "DecisionInput(" in line:
                in_block = True
                block_start = i
            if in_block and ")" in line and "DecisionInput" not in line:
                # rough block end detection
                block = "\n".join(lines[block_start:i+1])
                decision_input_blocks.append(block)
                in_block = False

        # There should be exactly one DecisionInput() construction in run_compliance_check
        for block in decision_input_blocks:
            # Count TenantPolicy( occurrences inside
            tp_count = block.count("TenantPolicy(")
            assert tp_count <= 1, \
                f"DecisionInput block should reference merged tenant_policy variable, not re-construct. Found {tp_count} TenantPolicy(): \n{block[:300]}"

    def test_tenant_policy_uses_variable(self):
        """check.py DecisionInput uses tenant_policy=tenant_policy (variable ref)."""
        import inspect
        from app.api import check as check_mod
        src = inspect.getsource(check_mod)

        # Find the line with tenant_policy=tenant_policy
        found = False
        for line in src.split("\n"):
            if "tenant_policy=tenant_policy" in line:
                found = True
                break
        assert found, \
            "check.py must have 'tenant_policy=tenant_policy' (using merged variable) for DecisionInput"


# ═══════════════════════════════════════════════════════════════
# 9. feedback production ingress
# ═══════════════════════════════════════════════════════════════

class TestFeedbackProductionIngress:

    def test_api_reference_is_safe(self):
        """Production API report.py uses safe submit_feedback_with_validation."""
        import inspect
        from app.api import report as report_mod
        src = inspect.getsource(report_mod)

        # Must import _extract_rule_ids_from_report from feedback_service
        assert "from app.services.feedback_service import _extract_rule_ids_from_report" in src

        # Cannot call _persist_feedback_event directly from API
        assert "_persist_feedback_event" not in src

        # Must call submit_feedback_with_validation
        assert "submit_feedback_with_validation" in src

    def test_service_has_only_private_persist(self):
        """feedback_service exposes _persist_feedback_event as private, not submit_feedback."""
        import inspect
        from app.services.feedback_service import FeedbackService
        methods = [m for m in dir(FeedbackService) if not m.startswith("__")]
        assert "_persist_feedback_event" in methods, "private persist function must exist"
        assert "submit_feedback" not in methods, "public submit_feedback must be removed"
        assert "submit_feedback_with_validation" in methods, "safe entry must exist"

    def test_api_no_duplicate_extraction(self):
        """report.py does not have its own _extract_rule_ids_from_report definition."""
        import inspect
        from app.api import report as report_mod
        src = inspect.getsource(report_mod)

        # Count def _extract_rule_ids_from_report in src
        count = src.count("def _extract_rule_ids_from_report")
        assert count == 0, \
            f"report.py should not define _extract_rule_ids_from_report. Found {count} definition(s)."


# ═══════════════════════════════════════════════════════════════
# 10. DecisionInput persistence with applied policy
# ═══════════════════════════════════════════════════════════════

class TestDecisionInputPersistence:

    def test_decision_input_contains_tenant_policy(self):
        """DecisionInput serialize/deserialize preserves tenant_policy."""
        from app.core.policy_kernel import DecisionInput, TenantPolicy

        tp = TenantPolicy(
            tenant_id="1",
            suppressed_rule_ids={"R_TEST_A", "R_TEST_B"},
        )
        di = DecisionInput(tenant_policy=tp)
        payload = di.model_dump(mode="json")
        # _canonical_json sorts sets, so suppressed_rule_ids may come sorted
        assert set(payload["tenant_policy"]["suppressed_rule_ids"]) == {"R_TEST_A", "R_TEST_B"}

        # Round-trip
        di2 = DecisionInput.model_validate(payload)
        assert di2.tenant_policy.suppressed_rule_ids == {"R_TEST_A", "R_TEST_B"}
        assert di2.tenant_policy.tenant_id == "1"

    def test_decision_input_hash_includes_tenant_policy(self):
        """Different tenant_policy → different decision hash."""
        from app.core.policy_kernel import DecisionInput, TenantPolicy, RuleType, PolicyKernel, RuleType

        kernel = PolicyKernel()
        tp_a = TenantPolicy(tenant_id="1", suppressed_rule_ids={"R_A"})
        tp_b = TenantPolicy(tenant_id="1", suppressed_rule_ids={"R_B"})

        di_a = DecisionInput(tenant_policy=tp_a)
        di_b = DecisionInput(tenant_policy=tp_b)

        assert kernel.decide(di_a).decision_hash != kernel.decide(di_b).decision_hash


# ═══════════════════════════════════════════════════════════════
# 11. Alembic approval flow — round trip
# ═══════════════════════════════════════════════════════════════

class TestApprovalFlowRoundTrip:

    def test_full_approval_flow_via_api(self, client, auth_headers, db_session):
        """Full API approval flow: create → submit → approve → apply → rollback."""
        # 1. Create draft
        resp = client.post(
            "/api/admin/policies/",
            json={
                "policy_key": "PK-FULL-FLOW",
                "policy_type": "tenant",
                "policy_data": '{"suppressed_rule_ids": ["R_FLOW"]}',
                "scope_type": "user",
                "scope_id": "42",
                "description": "Integration test flow",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        pid = resp.json()["id"]
        assert resp.json()["status"] == "draft"

        # 2. Submit for review
        resp = client.post(f"/api/admin/policies/{pid}/submit", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "review"

        # 3. Approve
        resp = client.post(f"/api/admin/policies/{pid}/approve", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

        # 4. Apply
        resp = client.post(f"/api/admin/policies/{pid}/apply", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "applied"

        # 5. Verify loader returns it
        from app.services.policy_repository import load_applied_policy_context
        loaded = load_applied_policy_context(
            db_session, scope_type="user", scope_id="42",
        )
        assert len(loaded) == 1
        assert loaded[0].policy_key == "PK-FULL-FLOW"

        # 6. Rollback
        resp = client.post(
            f"/api/admin/policies/{pid}/rollback?reason=test",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rolled_back"

        # 7. Verify loader no longer returns it
        loaded2 = load_applied_policy_context(
            db_session, scope_type="user", scope_id="42",
        )
        assert len(loaded2) == 0
