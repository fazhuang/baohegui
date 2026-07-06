""" Policy scope integration — phase 2: strict schema, platform wiring, constraints, audit

New coverage beyond test_policy_scope_integration.py phase 1:
  A. Strict policy_data schema (TenantPolicyData / PlatformPolicyData)
  B. Platform DynamicPolicy wired into check.py execution chain
  C. DB CHECK constraints + historical migration safety
  D. Policy API audit logging
"""

from __future__ import annotations

import json as _json
import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect, text

from app.services.policy_repository import DynamicPolicy
from app.services.policy_schema import (
    TenantPolicyData,
    PlatformPolicyData,
    validate_policy_data,
    normalize_policy_data,
    build_effective_tenant_policy,
    build_effective_platform_policy,
)
from app.core.policy_kernel import (
    TenantPolicy,
    PlatformPolicy,
    DecisionInput,
    PolicyKernel,
    RuleType,
)


# ═══════════════════════════════════════════════════════════════
# A. Strict policy_data schema — positive + adversarial cases
# ═══════════════════════════════════════════════════════════════

class TestPolicyDataValidation:

    def test_valid_tenant_policy_accepted(self):
        """Valid tenant schema accepted."""
        validated = validate_policy_data(
            "tenant",
            '{"suppressed_rule_ids": ["R001", "R002"], "auto_fail_rule_types": ["forbidden"]}',
        )
        assert isinstance(validated, TenantPolicyData)
        assert validated.suppressed_rule_ids == ["R001", "R002"]
        assert validated.auto_fail_rule_types == [RuleType.FORBIDDEN]

    def test_valid_platform_policy_accepted(self):
        """Valid platform schema accepted."""
        validated = validate_policy_data(
            "platform",
            '{"required_sections": ["招标公告", "技术规格"]}',
        )
        assert isinstance(validated, PlatformPolicyData)
        assert validated.required_sections == ["招标公告", "技术规格"]

    def test_normalize_round_trip_deterministic(self):
        """Normalize preserves schema fields with consistent typing.
        Same input → same output (deterministic for identical input)."""
        n1 = normalize_policy_data("tenant", '{"suppressed_rule_ids":["R001","R002"],"auto_fail_rule_types":["forbidden"]}')
        n2 = normalize_policy_data("tenant", '{"suppressed_rule_ids":["R001","R002"],"auto_fail_rule_types":["forbidden"]}')
        assert n1 == n2, "identical input must produce identical output"

    # ── Adversarial: suppressed_rule_ids ──

    def test_string_not_list_rejected(self):
        """{"suppressed_rule_ids":"R001"} — rejected (string, not list)."""
        with pytest.raises(ValueError, match="suppressed_rule_ids"):
            validate_policy_data("tenant", '{"suppressed_rule_ids":"R001"}')

    def test_mixed_array_rejected(self):
        """{"suppressed_rule_ids":[1,"R001"]} — rejected (int in list)."""
        with pytest.raises(ValueError, match="suppressed_rule_ids"):
            validate_policy_data("tenant", '{"suppressed_rule_ids":[1,"R001"]}')

    def test_unknown_rule_type_rejected(self):
        """{"auto_fail_rule_types":["unknown"]} — rejected (unknown enum)."""
        with pytest.raises(ValueError, match="auto_fail_rule_types"):
            validate_policy_data("tenant", '{"auto_fail_rule_types":["unknown"]}')

    def test_unknown_field_rejected(self):
        """extra=forbid: unknown top-level field rejected."""
        with pytest.raises(ValueError, match="unknown_field"):
            validate_policy_data("tenant", '{"unknown_field":[]}')

    def test_non_json_object_rejected(self):
        """Non-JSON-object rejected."""
        with pytest.raises(ValueError, match="JSON 对象"):
            validate_policy_data("tenant", '"just a string"')

    def test_malformed_json_rejected(self):
        """Malformed JSON rejected."""
        with pytest.raises(ValueError, match="JSON 解析失败"):
            validate_policy_data("tenant", "{not valid")

    def test_tenant_payload_for_platform_rejected(self):
        """tenant-only fields rejected when used for platform policy (extra=forbid)."""
        with pytest.raises(ValueError, match="suppressed_rule_ids"):
            validate_policy_data(
                "platform",
                '{"suppressed_rule_ids":["R001"],"required_sections":["A"]}',
            )

    def test_unsupported_policy_type_ux_rejected(self):
        """ux policy type rejected (not wired into execution chain)."""
        with pytest.raises(ValueError, match="不支持的 policy_type"):
            validate_policy_data("ux", '{"collapse_threshold":10}')

    # ── create_draft with strict schema ──

    def test_create_draft_rejects_bad_schema(self, db_session):
        """create_draft rejects suppressed_rule_ids as string."""
        from app.services.policy_repository import create_draft
        with pytest.raises(ValueError, match="suppressed_rule_ids"):
            create_draft(
                db_session,
                policy_key="PK-BAD-DRAFT",
                policy_type="tenant",
                policy_data='{"suppressed_rule_ids":"R001"}',
                scope_type="user", scope_id="1",
                created_by=1,
            )

    def test_create_draft_rejects_unsupported_type(self, db_session):
        """create_draft rejects ux policy_type."""
        from app.services.policy_repository import create_draft
        with pytest.raises(ValueError, match="不支持的 policy_type"):
            create_draft(
                db_session,
                policy_key="PK-UX-DRAFT",
                policy_type="ux",
                policy_data='{"collapse_threshold":10}',
                scope_type="user", scope_id="1",
                created_by=1,
            )

    # ── Apply-time schema re-validation ──

    def test_apply_revalidates_schema(self, db_session):
        """Modifying policy_data after approval → apply rejects bad schema."""
        from app.services.policy_repository import (
            create_draft, submit_for_review, approve, apply,
        )
        p = create_draft(
            db_session, policy_key="PK-APPLY-REVAL", policy_type="tenant",
            policy_data='{"suppressed_rule_ids": ["R_OK"]}',
            scope_type="user", scope_id="1", created_by=1,
        )
        p2 = submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p2.id, admin_id=1)
        # Tamper: set suppressed_rule_ids to string after approval
        p.policy_data = '{"suppressed_rule_ids":"R_BAD_STRING"}'
        db_session.commit()
        with pytest.raises(ValueError, match="suppressed_rule_ids"):
            apply(db_session, p.id, admin_id=1)

    # ── Historical illegal applied policy rejected by loader ──

    def test_loader_excludes_invalid_applied_policy(self, db_session):
        """Loader skips applied policy with invalid schema — does not enter execution chain."""
        from app.services.policy_repository import load_applied_policy_context
        # Directly insert a bad applied record (simulating historical corruption)
        dp = DynamicPolicy(
            policy_key="PK-BAD-HISTORY",
            policy_type="tenant",
            policy_data='{"suppressed_rule_ids":"R_BAD_STRING"}',
            status="applied",
            scope_type="user", scope_id="1",
            approved_by=1, approved_at=_json.loads("{}") or None,
        )
        from datetime import datetime, timezone
        dp.approved_at = datetime.now(timezone.utc)
        db_session.add(dp)
        db_session.commit()

        loaded = load_applied_policy_context(
            db_session, policy_type="tenant",
            scope_type="user", scope_id="1",
        )
        assert len(loaded) == 0, \
            f"illegal applied policy must be excluded by loader, got {len(loaded)}"

    def test_loader_does_not_return_historical_global_applied(self, db_session):
        """Historical applied global=global policy must be excluded by migration OR by loader."""
        from app.services.policy_repository import load_applied_policy_context
        # Simulate historical: applied with global/global
        dp = DynamicPolicy(
            policy_key="PK-OLD-GLOBAL",
            policy_type="tenant",
            policy_data='{"suppressed_rule_ids": ["R_OLD"]}',
            status="applied",
            scope_type="global", scope_id="global",
            approved_by=1,
        )
        from datetime import datetime, timezone
        dp.approved_at = datetime.now(timezone.utc)
        db_session.add(dp)
        db_session.commit()

        # user scope loader must NOT see it
        r = load_applied_policy_context(
            db_session, scope_type="user", scope_id="1",
        )
        assert len(r) == 0, f"global applied should not be visible to user-1, got {len(r)}"

        # global scope loader: may see it IF it passes schema (it does here, since schema is valid)
        r_global = load_applied_policy_context(
            db_session, scope_type="global", scope_id="global",
        )
        # global policy visible only with explicit global/global scope
        assert len(r_global) == 1


# ═══════════════════════════════════════════════════════════════
# B. Platform DynamicPolicy wired into check.py execution chain
# ═══════════════════════════════════════════════════════════════

class TestPlatformPolicyWired:

    def test_platform_policy_enters_platform_policy(self, db_session):
        """Applied platform-A policy required_sections enters PlatformPolicy."""
        from app.services.policy_repository import (
            create_draft, submit_for_review, approve, apply,
            load_applied_policy_context,
        )

        # Create and apply a platform policy for guangdong
        p = create_draft(
            db_session, policy_key="PK-PLAT-WIRED-1", policy_type="platform",
            policy_data='{"required_sections": ["动态附加章节"]}',
            scope_type="platform", scope_id="guangdong",
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)
        apply(db_session, p.id, admin_id=1)

        # Simulate what check.py does
        base = PlatformPolicy(platform_id="guangdong", required_sections={"招标公告"})
        applied = load_applied_policy_context(
            db_session, policy_type="platform",
            scope_type="platform", scope_id="guangdong",
        )
        result = build_effective_platform_policy(base, applied)

        assert "招标公告" in result.required_sections, "built-in sections must be preserved"
        assert "动态附加章节" in result.required_sections, "dynamic sections must be added"
        assert result.platform_id == "guangdong"

    def test_platform_b_not_affected(self, db_session):
        """Platform-A policy does NOT affect Platform-B."""
        from app.services.policy_repository import (
            create_draft, submit_for_review, approve, apply,
            load_applied_policy_context,
        )

        p = create_draft(
            db_session, policy_key="PK-PLAT-A-ONLY", policy_type="platform",
            policy_data='{"required_sections": ["GD_SECTION"]}',
            scope_type="platform", scope_id="guangdong",
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)
        apply(db_session, p.id, admin_id=1)

        base_b = PlatformPolicy(platform_id="jiangsu", required_sections={"内置章节"})
        applied_b = load_applied_policy_context(
            db_session, policy_type="platform",
            scope_type="platform", scope_id="jiangsu",
        )
        result_b = build_effective_platform_policy(base_b, applied_b)
        assert "GD_SECTION" not in result_b.required_sections

    def test_dynamic_cannot_remove_builtin(self, db_session):
        """Dynamic policy cannot remove built-in required sections — only union."""
        from app.services.policy_repository import (
            create_draft, submit_for_review, approve, apply,
            load_applied_policy_context,
        )

        p = create_draft(
            db_session, policy_key="PK-UNION-ONLY", policy_type="platform",
            policy_data='{"required_sections": ["附加章节"]}',
            scope_type="platform", scope_id="guangdong",
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)
        apply(db_session, p.id, admin_id=1)

        base = PlatformPolicy(platform_id="guangdong", required_sections={"内置章节"})
        applied = load_applied_policy_context(
            db_session, policy_type="platform",
            scope_type="platform", scope_id="guangdong",
        )
        result = build_effective_platform_policy(base, applied)
        assert "内置章节" in result.required_sections, "built-in must be preserved"
        assert "附加章节" in result.required_sections, "dynamic must be added"
        # Both must be present — union, not replacement
        assert len(result.required_sections) >= 2

    def test_non_applied_platform_not_effective(self, db_session):
        """Draft/review/approved/rolled_back platform policy does NOT enter PlatformPolicy."""
        from app.services.policy_repository import (
            create_draft, submit_for_review, approve, load_applied_policy_context,
        )

        # Create and bring to approved, but NOT applied
        p = create_draft(
            db_session, policy_key="PK-PLAT-APPROVED", policy_type="platform",
            policy_data='{"required_sections": ["SHOULD_NOT_APPEAR"]}',
            scope_type="platform", scope_id="guangdong",
            created_by=1,
        )
        submit_for_review(db_session, p.id, admin_id=1)
        approve(db_session, p.id, admin_id=1)

        base = PlatformPolicy(platform_id="guangdong")
        applied = load_applied_policy_context(
            db_session, policy_type="platform",
            scope_type="platform", scope_id="guangdong",
        )
        result = build_effective_platform_policy(base, applied)
        assert "SHOULD_NOT_APPEAR" not in result.required_sections, \
            "approved (not applied) platform policy must not be effective"

    def test_decision_input_includes_platform_policy(self):
        """DecisionInput serialization includes platform_policy sections."""
        pp = PlatformPolicy(platform_id="guangdong", required_sections={"招标公告", "动态章节"})
        di = DecisionInput(platform_policy=pp)
        payload = di.model_dump(mode="json")
        assert "招标公告" in payload["platform_policy"]["required_sections"]
        assert "动态章节" in payload["platform_policy"]["required_sections"]

    def test_different_platform_hashes_differ(self):
        """Different platform policies → different input_hash and decision_hash."""
        kernel = PolicyKernel()
        pp_a = PlatformPolicy(platform_id="guangdong", required_sections={"A"})
        pp_b = PlatformPolicy(platform_id="jiangsu", required_sections={"B"})
        di_a = DecisionInput(platform_policy=pp_a)
        di_b = DecisionInput(platform_policy=pp_b)
        d_a = kernel.decide(di_a)
        d_b = kernel.decide(di_b)
        assert d_a.input_hash != d_b.input_hash
        assert d_a.decision_hash != d_b.decision_hash

    def test_check_py_uses_build_effective_platform_policy(self):
        """check.py imports build_effective_platform_policy."""
        import inspect
        from app.api import check as check_mod
        src = inspect.getsource(check_mod)
        assert "build_effective_platform_policy" in src, \
            "check.py must use build_effective_platform_policy"
        assert "build_effective_tenant_policy" in src, \
            "check.py must use build_effective_tenant_policy"


# ═══════════════════════════════════════════════════════════════
# C. DB CHECK constraints + historical migration safety
# ═══════════════════════════════════════════════════════════════

class TestDBCheckConstraints:

    @pytest.fixture(scope="class")
    def constrained_engine(self):
        """SQLite database with CHECK constraints via full Alembic upgrade to 1200 head."""
        import uuid
        import tempfile
        # Use unique path per test suite run to avoid cross-test pollution
        db_path = os.path.join(
            tempfile.gettempdir(),
            f"bhg_policy_constraints_test_{uuid.uuid4().hex}.db"
        )
        if os.path.exists(db_path):
            os.unlink(db_path)

        from alembic.config import Config
        from alembic import command
        from pathlib import Path

        alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
        alembic_cfg = Config(str(alembic_ini))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

        # Override env.py's URL reading by monkeypatching settings
        import app.core.config as cfg_mod
        old_url = cfg_mod.settings.database_url
        cfg_mod.settings.database_url = f"sqlite:///{db_path}"

        try:
            # Upgrade to 1100, insert historical record, then upgrade to 1200
            command.upgrade(alembic_cfg, "20260707_1100_policy_scope")

            engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

            from datetime import datetime, timezone
            now_ts = datetime.now(timezone.utc).isoformat()
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO dynamic_policies (policy_key, policy_type, policy_data, status, "
                    "scope_type, scope_id, created_by, created_at, updated_at) VALUES "
                    "('PK-HISTORIC', 'tenant', :pd, "
                    "'applied', 'global', 'global', 1, :now, :now)"
                ), {"pd": '{"suppressed_rule_ids": ["R_OLD"]}', "now": now_ts})

            # Upgrade to 1200
            command.upgrade(alembic_cfg, "20260707_1200_policy_constraints")

            yield engine

            engine.dispose()
        finally:
            cfg_mod.settings.database_url = old_url
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_historical_global_applied_rolled_back(self, constrained_engine):
        """Historical global applied policy → rolled_back after 1200 migration."""
        with constrained_engine.begin() as conn:
            row = conn.execute(text(
                "SELECT status, rollback_reason FROM dynamic_policies WHERE policy_key='PK-HISTORIC'"
            )).fetchone()
        assert row[0] == "rolled_back", f"historical applied must be rolled_back, got {row[0]}"
        assert "migration_scope_unverifiable" in row[1]

    def test_scope_type_check_exists(self, constrained_engine):
        """CHECK constraint on scope_type exists in DB."""
        inspector = inspect(constrained_engine)
        # For SQLite, check by trying invalid insert
        with constrained_engine.begin() as conn:
            try:
                conn.execute(text(
                    "INSERT INTO dynamic_policies (policy_key, policy_type, policy_data, status, "
                    "scope_type, scope_id, created_by) VALUES "
                    "('PK-BAD-SCOPE', 'tenant', '{\"suppressed_rule_ids\": [\"R_X\"]}', "
                    "'draft', 'invalid_scope', '1', 1)"
                ))
                # If we get here, the CHECK failed — that's actually a bug
                # Let's verify by reading it back
                row = conn.execute(text(
                    "SELECT scope_type FROM dynamic_policies WHERE policy_key='PK-BAD-SCOPE'"
                )).fetchone()
                if row is not None:
                    pytest.fail("CHECK constraint on scope_type must reject 'invalid_scope'")
            except Exception:
                # Expected: CHECK constraint rejects invalid scope_type
                pass

    def test_status_check_exists(self, constrained_engine):
        """CHECK constraint on status rejects invalid status."""
        with constrained_engine.begin() as conn:
            with pytest.raises(Exception):
                conn.execute(text(
                    "INSERT INTO dynamic_policies (policy_key, policy_type, policy_data, status, "
                    "scope_type, scope_id, created_by) VALUES "
                    "('PK-BAD-STATUS', 'tenant', '{\"suppressed_rule_ids\": [\"R_X\"]}', "
                    "'invalid_status', 'user', '1', 1)"
                ))

    def test_policy_type_check_exists(self, constrained_engine):
        """CHECK constraint on policy_type rejects invalid policy_type."""
        with constrained_engine.begin() as conn:
            with pytest.raises(Exception):
                conn.execute(text(
                    "INSERT INTO dynamic_policies (policy_key, policy_type, policy_data, status, "
                    "scope_type, scope_id, created_by) VALUES "
                    "('PK-BAD-TYPE', 'ux_invalid', '{}', "
                    "'draft', 'user', '1', 1)"
                ))

    def test_null_scope_type_rejected(self, constrained_engine):
        """NOT NULL on scope_type must reject null."""
        with constrained_engine.begin() as conn:
            with pytest.raises(Exception):
                conn.execute(text(
                    "INSERT INTO dynamic_policies (policy_key, policy_type, policy_data, status, "
                    "scope_type, scope_id, created_by) VALUES "
                    "('PK-NULL-SCOPE', 'tenant', '{\"suppressed_rule_ids\": [\"R_X\"]}', "
                    "'draft', NULL, '1', 1)"
                ))

    def test_full_upgrade_from_empty_succeeds(self):
        """Fresh DB upgrade head from empty succeeds."""
        import tempfile
        db_path = os.path.join(tempfile.gettempdir(), "bhg_empty_upgrade_strict_test.db")
        if os.path.exists(db_path):
            os.unlink(db_path)

        from alembic.config import Config
        from alembic import command
        from pathlib import Path

        alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
        alembic_cfg = Config(str(alembic_ini))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        import app.core.config as cfg_mod
        cfg_mod.settings.database_url = f"sqlite:///{db_path}"

        try:
            command.upgrade(alembic_cfg, "head")
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ═══════════════════════════════════════════════════════════════
# D. Policy API audit logging
# ═══════════════════════════════════════════════════════════════

class TestPolicyAudit:

    def test_create_audit(self, client, auth_headers, db_session):
        """Create produces policy_create audit."""
        from app.core.audit import AuditLog
        before = db_session.query(AuditLog).count()

        resp = client.post(
            "/api/admin/policies/",
            json={
                "policy_key": "PK-AUDIT-CREATE",
                "policy_type": "tenant",
                "policy_data": '{"suppressed_rule_ids": ["R_AUDIT"]}',
                "scope_type": "user",
                "scope_id": "1",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201

        after = db_session.query(AuditLog).count()
        assert after > before, "audit log must be written for policy_create"

        # Check the last audit entry
        last = db_session.query(AuditLog).order_by(AuditLog.id.desc()).first()
        assert last.action == "policy_create"
        assert last.resource == "dynamic_policy"
        detail = _json.loads(last.detail or "{}")
        assert detail["to_status"] == "draft"
        assert detail["policy_key"] == "PK-AUDIT-CREATE"
        assert "policy_data" not in detail or isinstance(detail.get("policy_data"), str)
        # Must contain hash, not raw data
        assert "policy_data_hash" in detail

    def test_full_approval_flow_audit(self, client, auth_headers, db_session):
        """Submit → approve → apply → rollback each produces audit."""
        from app.core.audit import AuditLog

        # Create
        resp = client.post(
            "/api/admin/policies/",
            json={
                "policy_key": "PK-AUDIT-FLOW",
                "policy_type": "tenant",
                "policy_data": '{"suppressed_rule_ids": ["R_FLOW_AUDIT"]}',
                "scope_type": "user",
                "scope_id": "42",
            },
            headers=auth_headers,
        )
        pid = resp.json()["id"]

        # Submit
        resp = client.post(f"/api/admin/policies/{pid}/submit", headers=auth_headers)
        assert resp.status_code == 200

        # Approve
        resp = client.post(f"/api/admin/policies/{pid}/approve?note=通过", headers=auth_headers)
        assert resp.status_code == 200

        # Apply
        resp = client.post(f"/api/admin/policies/{pid}/apply", headers=auth_headers)
        assert resp.status_code == 200

        # Rollback
        resp = client.post(f"/api/admin/policies/{pid}/rollback?reason=测试回滚", headers=auth_headers)
        assert resp.status_code == 200

        # Verify audit sequence
        logs = db_session.query(AuditLog).filter(
            AuditLog.resource == "dynamic_policy",
            AuditLog.resource_id == str(pid),
        ).order_by(AuditLog.id).all()

        actions = [log.action for log in logs]
        assert "policy_create" in actions
        assert "policy_submit" in actions
        assert "policy_approve" in actions
        assert "policy_apply" in actions
        assert "policy_rollback" in actions

        # Verify rollback contains reason
        rollback_log = [log for log in logs if log.action == "policy_rollback"][0]
        detail = _json.loads(rollback_log.detail or "{}")
        assert detail["note"] == "测试回滚"
        assert detail["to_status"] == "rolled_back"

    def test_reject_and_revise_audit(self, client, auth_headers, db_session):
        """Reject and revise produce correct audits."""
        from app.core.audit import AuditLog

        resp = client.post(
            "/api/admin/policies/",
            json={
                "policy_key": "PK-AUDIT-REJECT",
                "policy_type": "tenant",
                "policy_data": '{"suppressed_rule_ids": ["R_REJ"]}',
                "scope_type": "user",
                "scope_id": "1",
            },
            headers=auth_headers,
        )
        pid = resp.json()["id"]
        client.post(f"/api/admin/policies/{pid}/submit", headers=auth_headers)
        client.post(f"/api/admin/policies/{pid}/reject?reason=不符合要求", headers=auth_headers)
        client.post(f"/api/admin/policies/{pid}/revise", headers=auth_headers)

        logs = db_session.query(AuditLog).filter(
            AuditLog.resource == "dynamic_policy",
            AuditLog.resource_id == str(pid),
        ).order_by(AuditLog.id).all()

        actions = [log.action for log in logs]
        assert "policy_reject" in actions
        assert "policy_revise" in actions

        reject_log = [log for log in logs if log.action == "policy_reject"][0]
        detail = _json.loads(reject_log.detail or "{}")
        assert detail["note"] == "不符合要求"
        assert detail["to_status"] == "rejected"

    def test_non_admin_no_success_audit(self, client, user_auth_headers, db_session):
        """Non-admin creation returns 403, no successful audit."""
        from app.core.audit import AuditLog
        before = db_session.query(AuditLog).count()

        resp = client.post(
            "/api/admin/policies/",
            json={
                "policy_key": "PK-NA-AUDIT",
                "policy_type": "tenant",
                "policy_data": '{"suppressed_rule_ids": ["R_NA"]}',
                "scope_type": "user",
                "scope_id": "1",
            },
            headers=user_auth_headers,
        )
        assert resp.status_code == 403

        after = db_session.query(AuditLog).count()
        # No new audit for the policy_create action itself
        new_logs = db_session.query(AuditLog).filter(
            AuditLog.action == "policy_create",
            AuditLog.resource_id.isnot(None),
        ).all()
        # All should have resource_id not matching a rejected creation
        assert after == before or all(
            _json.loads((log.detail or "{}")).get("policy_key") != "PK-NA-AUDIT"
            for log in new_logs
        )

    def test_illegal_transition_no_success_audit(self, client, auth_headers, db_session):
        """Illegal draft→apply produces no success audit."""
        from app.core.audit import AuditLog

        resp = client.post(
            "/api/admin/policies/",
            json={
                "policy_key": "PK-ILLEGAL-AUDIT",
                "policy_type": "tenant",
                "policy_data": '{"suppressed_rule_ids": ["R_ILLEGAL"]}',
                "scope_type": "user",
                "scope_id": "1",
            },
            headers=auth_headers,
        )
        pid = resp.json()["id"]

        before = db_session.query(AuditLog).count()
        resp = client.post(f"/api/admin/policies/{pid}/apply", headers=auth_headers)
        assert resp.status_code == 400  # Expected: cannot apply draft

        after = db_session.query(AuditLog).count()
        # No new policy_apply audit should exist
        apply_logs = db_session.query(AuditLog).filter(
            AuditLog.action == "policy_apply",
            AuditLog.resource_id == str(pid),
        ).all()
        assert len(apply_logs) == 0, "illegal transition must not produce success audit"

    def test_audit_does_not_contain_raw_policy_data(self, client, auth_headers, db_session):
        """Audit detail must not contain raw policy_data string."""
        from app.core.audit import AuditLog

        resp = client.post(
            "/api/admin/policies/",
            json={
                "policy_key": "PK-SENSITIVE",
                "policy_type": "tenant",
                "policy_data": '{"suppressed_rule_ids": ["R_SECRET_001"]}',
                "scope_type": "user",
                "scope_id": "99",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201

        all_logs = db_session.query(AuditLog).filter(
            AuditLog.action == "policy_create",
        ).order_by(AuditLog.id.desc()).limit(1).all()

        for log in all_logs:
            detail = _json.loads(log.detail or "{}")
            # Must not contain full policy_data text
            assert "R_SECRET_001" not in str(detail), \
                f"audit must not contain raw suppressed_rule_ids: {detail}"
            assert "suppressed_rule_ids" not in detail, \
                f"audit must not contain policy fields: {detail}"
            assert "policy_data_hash" in detail, "audit must contain hash instead"
