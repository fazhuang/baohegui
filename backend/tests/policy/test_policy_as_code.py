"""Tests for Policy-as-Code layer."""
import pytest
from datetime import datetime, timedelta, timezone
from app.policy.policy_actions import PolicyAction
from app.policy.policy_definition import PolicyDefinition
from app.policy.policy_evaluator import PolicyEvaluator, PolicyContext


class TestPolicyAction:
    def test_no_disable_hard_rule(self):
        """DISABLE_HARD_RULE must never exist."""
        actions = {a.value for a in PolicyAction}
        assert "disable_hard_rule" not in actions
        assert "DISABLE_HARD_RULE" not in actions

    def test_escalate_actions_exist(self):
        assert PolicyAction.ESCALATE_TO_YELLOW
        assert PolicyAction.ESCALATE_TO_RED

    def test_human_review_action_exists(self):
        assert PolicyAction.REQUIRE_HUMAN_REVIEW


class TestPolicyDefinition:
    def test_create_definition(self):
        pd = PolicyDefinition(
            policy_id="P001",
            policy_type="TENANT",
            scope="tenant:t1",
            priority=10,
            condition={"field": "budget", "op": "gte", "value": 5000000},
            action=PolicyAction.ESCALATE_TO_RED,
            effective_from=datetime.now(timezone.utc),
            expires_at=None,
            approved_by="admin",
            version=1,
        )
        assert pd.policy_id == "P001"
        assert pd.policy_type == "TENANT"
        assert pd.action == PolicyAction.ESCALATE_TO_RED

    def test_expired_policy(self):
        pd = PolicyDefinition(
            policy_id="P002",
            policy_type="UX",
            scope="global",
            priority=1,
            condition={},
            action=PolicyAction.ESCALATE_TO_YELLOW,
            effective_from=datetime.now(timezone.utc) - timedelta(days=30),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            approved_by="admin",
            version=1,
        )
        assert pd.is_expired() is True

    def test_not_yet_effective_policy(self):
        pd = PolicyDefinition(
            policy_id="P003",
            policy_type="UX",
            scope="global",
            priority=1,
            condition={},
            action=PolicyAction.ESCALATE_TO_YELLOW,
            effective_from=datetime.now(timezone.utc) + timedelta(days=30),
            expires_at=None,
            approved_by="admin",
            version=1,
        )
        assert pd.is_effective() is False


class TestPolicyEvaluator:
    def test_no_policies_returns_empty(self):
        evaluator = PolicyEvaluator(policies=[])
        context = PolicyContext(tenant_id="t1", industry="construction", budget=1000000)
        actions = evaluator.evaluate(context)
        assert actions == []

    def test_matching_condition(self):
        pd = PolicyDefinition(
            policy_id="P001",
            policy_type="TENANT",
            scope="global",
            priority=10,
            condition={"field": "budget", "op": "gte", "value": 5000000},
            action=PolicyAction.ESCALATE_TO_RED,
            effective_from=datetime.now(timezone.utc) - timedelta(days=1),
            expires_at=None,
            approved_by="admin",
            version=1,
        )
        evaluator = PolicyEvaluator(policies=[pd])
        context = PolicyContext(tenant_id="t1", industry="construction", budget=6000000)
        actions = evaluator.evaluate(context)
        assert PolicyAction.ESCALATE_TO_RED in actions

    def test_non_matching_condition(self):
        pd = PolicyDefinition(
            policy_id="P001",
            policy_type="TENANT",
            scope="global",
            priority=10,
            condition={"field": "budget", "op": "gte", "value": 5000000},
            action=PolicyAction.ESCALATE_TO_RED,
            effective_from=datetime.now(timezone.utc) - timedelta(days=1),
            expires_at=None,
            approved_by="admin",
            version=1,
        )
        evaluator = PolicyEvaluator(policies=[pd])
        context = PolicyContext(tenant_id="t1", industry="construction", budget=100000)
        actions = evaluator.evaluate(context)
        assert actions == []

    def test_scope_filtering(self):
        pd = PolicyDefinition(
            policy_id="P001",
            policy_type="TENANT",
            scope="tenant:t2",
            priority=10,
            condition={},
            action=PolicyAction.ESCALATE_TO_YELLOW,
            effective_from=datetime.now(timezone.utc) - timedelta(days=1),
            expires_at=None,
            approved_by="admin",
            version=1,
        )
        evaluator = PolicyEvaluator(policies=[pd])
        context = PolicyContext(tenant_id="t1", industry="construction", budget=100000)
        actions = evaluator.evaluate(context)
        assert actions == []

    def test_priority_ordering(self):
        """Higher priority (lower number) wins on conflict."""
        pd1 = PolicyDefinition(
            policy_id="P001", policy_type="TENANT", scope="global",
            priority=1,
            condition={},
            action=PolicyAction.ESCALATE_TO_RED,
            effective_from=datetime.now(timezone.utc) - timedelta(days=1),
            expires_at=None, approved_by="admin", version=1,
        )
        pd2 = PolicyDefinition(
            policy_id="P002", policy_type="TENANT", scope="global",
            priority=10,
            condition={},
            action=PolicyAction.ESCALATE_TO_YELLOW,
            effective_from=datetime.now(timezone.utc) - timedelta(days=1),
            expires_at=None, approved_by="admin", version=1,
        )
        evaluator = PolicyEvaluator(policies=[pd2, pd1])  # unordered input
        context = PolicyContext(tenant_id="t1", industry="construction", budget=100000)
        actions = evaluator.evaluate(context)
        # Both match, but RED (priority 1) wins over YELLOW (priority 10)
        assert PolicyAction.ESCALATE_TO_RED in actions
        # YELLOW should be excluded because RED is a higher escalation
        assert actions == [PolicyAction.ESCALATE_TO_RED]

    def test_expired_policy_not_evaluated(self):
        pd = PolicyDefinition(
            policy_id="P001", policy_type="UX", scope="global",
            priority=1, condition={},
            action=PolicyAction.ESCALATE_TO_RED,
            effective_from=datetime.now(timezone.utc) - timedelta(days=30),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            approved_by="admin", version=1,
        )
        evaluator = PolicyEvaluator(policies=[pd])
        context = PolicyContext(tenant_id="t1", industry="construction", budget=100000)
        actions = evaluator.evaluate(context)
        assert actions == []

    def test_not_yet_effective_policy_not_evaluated(self):
        pd = PolicyDefinition(
            policy_id="P001", policy_type="UX", scope="global",
            priority=1, condition={},
            action=PolicyAction.ESCALATE_TO_RED,
            effective_from=datetime.now(timezone.utc) + timedelta(days=30),
            expires_at=None,
            approved_by="admin", version=1,
        )
        evaluator = PolicyEvaluator(policies=[pd])
        context = PolicyContext(tenant_id="t1", industry="construction", budget=100000)
        actions = evaluator.evaluate(context)
        assert actions == []
