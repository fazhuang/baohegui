"""Replay consistency tests — verify AuditTrace hash-chain + replay integrity."""

from __future__ import annotations

import pytest

from app.core.replay_engine import (
    AuditTrace,
    StepSnapshot,
    _canonical_for_step,
    _make_step,
    replay_decision,
    verify_replay,
    sha256_hex,
    _canonical_json,
)
from app.core.policy_kernel import (
    DecisionInput,
    PolicyDecision,
    policy_kernel,
    DecisionAction,
    RiskLevel,
    RuleViolationInput,
    RuleType,
    RoutingInput,
    TrafficLight,
    TenantPolicy,
    PlatformPolicy,
    UxPolicy,
)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _make_decision_input(**overrides) -> DecisionInput:
    """Build a minimal valid DecisionInput for testing."""
    defaults = {
        "schema_version": "2.1.0",
        "routing": RoutingInput(traffic_light=TrafficLight.GREEN, skip_llm=False),
        "rule_violations": [],
        "bias_findings": [],
        "llm_violations": [],
        "parse_quality": "ok",
        "present_sections": set(),
        "tenant_policy": TenantPolicy(),
        "platform_policy": PlatformPolicy(),
        "ux_policy": UxPolicy(),
    }
    defaults.update(overrides)
    return DecisionInput(**defaults)


def _make_policy_decision(di: DecisionInput) -> PolicyDecision:
    """Run PolicyKernel and return the decision."""
    return policy_kernel.decide(di)


# ═══════════════════════════════════════════════════════════════
# Canonical JSON tests
# ═══════════════════════════════════════════════════════════════

class TestCanonicalJson:
    def test_dict_key_sorting(self):
        d = {"z": 1, "a": 2, "m": 3}
        result = _canonical_json(d).decode()
        assert result == '{"a":2,"m":3,"z":1}'

    def test_nested_sorting(self):
        d = {"outer": {"c": 3, "a": 1}, "inner": [2, 1]}
        result = _canonical_json(d).decode()
        assert '"a":1' in result
        assert '"c":3' in result

    def test_deterministic_across_runs(self):
        """Same input → same hash every time."""
        d = {"x": [3, 2, 1], "y": {"b": 2, "a": 1}}
        h1 = sha256_hex(_canonical_json(d))
        h2 = sha256_hex(_canonical_json(d))
        assert h1 == h2

    def test_different_input_different_hash(self):
        h1 = sha256_hex(_canonical_json({"a": 1}))
        h2 = sha256_hex(_canonical_json({"a": 2}))
        assert h1 != h2

    def test_step_canonical_is_deterministic(self):
        """_canonical_for_step produces same hash regardless of insertion order."""
        d1 = {"c": 3, "a": 1, "b": 2}
        d2 = {"a": 1, "b": 2, "c": 3}
        assert sha256_hex(_canonical_json(_canonical_for_step(d1))) == \
               sha256_hex(_canonical_json(_canonical_for_step(d2)))


# ═══════════════════════════════════════════════════════════════
# Hash chain tests
# ═══════════════════════════════════════════════════════════════

class TestHashChain:
    def test_chain_links(self):
        """Each step's input_hash equals previous step's output_hash."""
        steps = []
        prev = ""
        for name in ["input", "routing", "rule_engine"]:
            out = {"step": name, "value": len(name)}
            step = _make_step(name, prev, out)
            steps.append(step)
            if prev:
                assert step.input_hash == prev
            prev = step.output_hash

        assert len(steps) == 3

    def test_chain_break_detection(self):
        """Tampered hash chain fails verification."""
        trace = AuditTrace()
        s0 = _make_step("input", "", {"val": 0})
        s1 = _make_step("step1", s0.output_hash, {"val": 1})

        # Tamper: change s1's input_hash
        s1.input_hash = "deadbeef" * 8

        trace.steps = [s0, s1]
        trace.root_hash = s0.input_hash
        trace.terminal_hash = s1.output_hash
        trace.decision_hash = s1.output_hash

        result = trace.verify_chain()
        assert result["valid"] is False
        assert any("chain" in e.lower() for e in result["errors"])

    def test_output_hash_mismatch(self):
        """Tampered output_hash fails verification."""
        trace = AuditTrace()
        s0 = _make_step("input", "", {"val": 0})
        s1 = _make_step("step1", s0.output_hash, {"val": 1})

        # Tamper: change output_snapshot but not output_hash
        s1.output_snapshot = {"val": 999}  # tampered

        trace.steps = [s0, s1]
        trace.root_hash = s0.input_hash
        trace.terminal_hash = s1.output_hash
        trace.decision_hash = s1.output_hash

        result = trace.verify_chain()
        assert result["valid"] is False


# ═══════════════════════════════════════════════════════════════
# End-to-end replay tests
# ═══════════════════════════════════════════════════════════════

class TestEndToEndReplay:
    def test_build_and_replay_minimal(self):
        """Minimal pipeline trace: build trace, verify chain, replay decision."""
        di = _make_decision_input()
        pd = _make_policy_decision(di)

        trace = AuditTrace.from_pipeline(
            file_hash="abc123",
            file_name="test.pdf",
            routing_result=None,
            rule_result=None,
            bias_result=None,
            llm_result=None,
            decision_input=di,
            policy_decision=pd,
        )

        # Verify chain
        chain = trace.verify_chain()
        assert chain["valid"], f"Chain errors: {chain.get('errors')}"

        # Replay
        replayed = replay_decision(trace)
        assert replayed.decision_hash == pd.decision_hash
        assert replayed.final_action == pd.final_action
        assert replayed.final_risk_level == pd.final_risk_level
        assert replayed.requires_human_review == pd.requires_human_review

    def test_replay_with_rule_violation(self):
        """Trace with one forbidden violation affects decision deterministically."""
        di = _make_decision_input(
            rule_violations=[
                RuleViolationInput(
                    rule_id="R101",
                    rule_type=RuleType.FORBIDDEN,
                    risk_level=RiskLevel.HIGH,
                    description="禁止指定品牌",
                )
            ],
        )
        pd = _make_policy_decision(di)

        trace = AuditTrace.from_pipeline(
            file_hash="def456",
            file_name="biased.pdf",
            decision_input=di,
            policy_decision=pd,
        )

        chain = trace.verify_chain()
        assert chain["valid"], f"Chain errors: {chain.get('errors')}"

        replayed = replay_decision(trace)
        assert replayed.decision_hash == pd.decision_hash
        # single forbidden+high → HARD_RULE_FORBIDDEN_HIGH → BLOCK
        assert replayed.final_action == DecisionAction.BLOCK

    def test_same_input_same_hash(self):
        """Two traces from identical inputs produce identical decision_hash."""
        di1 = _make_decision_input()
        di2 = _make_decision_input()

        pd1 = _make_policy_decision(di1)
        pd2 = _make_policy_decision(di2)

        assert pd1.decision_hash == pd2.decision_hash
        assert pd1.final_action == pd2.final_action

    def test_different_input_different_hash(self):
        """Different inputs produce different decision_hash."""
        di1 = _make_decision_input()
        di2 = _make_decision_input(
            rule_violations=[
                RuleViolationInput(
                    rule_id="R102",
                    rule_type=RuleType.FORBIDDEN,
                    risk_level=RiskLevel.CRITICAL,
                    description="多个禁止项",
                ),
                RuleViolationInput(
                    rule_id="R103",
                    rule_type=RuleType.FORBIDDEN,
                    risk_level=RiskLevel.CRITICAL,
                    description="另一个禁止项",
                ),
            ],
        )

        pd1 = _make_policy_decision(di1)
        pd2 = _make_policy_decision(di2)

        assert pd1.decision_hash != pd2.decision_hash

    def test_verify_replay_full(self):
        """verify_replay exercises both chain verification and semantic replay."""
        di = _make_decision_input(
            rule_violations=[
                RuleViolationInput(
                    rule_id="R200",
                    rule_type=RuleType.CHAPTER_REQUIRED,
                    risk_level=RiskLevel.MEDIUM,
                    description="缺少章节",
                ),
            ],
            bias_findings=[],
        )
        pd = _make_policy_decision(di)

        trace = AuditTrace.from_pipeline(
            file_hash="ghi789",
            file_name="incomplete.pdf",
            decision_input=di,
            policy_decision=pd,
        )

        result = verify_replay(trace)
        assert result["valid"], f"Verify errors: {result.get('errors')}"
        assert result["checks"].get("decision_hash_match") is True
        assert result["checks"].get("policy_trace_valid") is True


# ═══════════════════════════════════════════════════════════════
# Serialization round-trip
# ═══════════════════════════════════════════════════════════════

class TestSerialization:
    def test_round_trip(self):
        """to_dict → from_dict is identity-preserving."""
        di = _make_decision_input(
            rule_violations=[
                RuleViolationInput(
                    rule_id="R300",
                    rule_type=RuleType.FORBIDDEN,
                    risk_level=RiskLevel.HIGH,
                    description="测试违规",
                ),
            ],
        )
        pd = _make_policy_decision(di)

        trace = AuditTrace.from_pipeline(
            file_hash="xyz000",
            file_name="roundtrip.pdf",
            decision_input=di,
            policy_decision=pd,
        )

        d = trace.to_dict()
        restored = AuditTrace.from_dict(d)

        assert restored.root_hash == trace.root_hash
        assert restored.decision_hash == trace.decision_hash
        assert restored.terminal_hash == trace.terminal_hash
        assert restored.file_hash == trace.file_hash
        assert restored.file_name == trace.file_name
        assert len(restored.steps) == len(trace.steps)

        # Verify chain survives round-trip
        chain = restored.verify_chain()
        assert chain["valid"], f"Round-trip chain broken: {chain.get('errors')}"

    def test_json_serializable(self):
        """to_dict() output is JSON-serializable."""
        import json

        di = _make_decision_input()
        pd = _make_policy_decision(di)
        trace = AuditTrace.from_pipeline(
            file_hash="json001",
            file_name="json.pdf",
            decision_input=di,
            policy_decision=pd,
        )

        d = trace.to_dict()
        # Should not raise
        s = json.dumps(d, ensure_ascii=False)
        assert len(s) > 0


# ═══════════════════════════════════════════════════════════════
# Tamper detection
# ═══════════════════════════════════════════════════════════════

class TestTamperDetection:
    def test_tampered_root_hash(self):
        """Changing root_hash breaks verification."""
        di = _make_decision_input()
        pd = _make_policy_decision(di)
        trace = AuditTrace.from_pipeline(
            file_hash="tamper1",
            file_name="tamper.pdf",
            decision_input=di,
            policy_decision=pd,
        )

        # Tamper root hash
        trace.root_hash = "deadbeef" * 8
        result = trace.verify_chain()
        assert result["valid"] is False

    def test_tampered_decision_hash(self):
        """verify_replay catches decision_hash mismatch."""
        di = _make_decision_input()
        pd = _make_policy_decision(di)
        trace = AuditTrace.from_pipeline(
            file_hash="tamper2",
            file_name="tamper2.pdf",
            decision_input=di,
            policy_decision=pd,
        )

        # Tamper stored decision_hash
        trace.decision_hash = "deadbeef" * 8
        result = verify_replay(trace)
        assert result["valid"] is False
        assert result["checks"].get("decision_hash_match") is False

    def test_tampered_decision_input(self):
        """Changing the stored DecisionInput changes the replayed decision."""
        di = _make_decision_input()
        pd = _make_policy_decision(di)
        trace = AuditTrace.from_pipeline(
            file_hash="tamper3",
            file_name="tamper3.pdf",
            decision_input=di,
            policy_decision=pd,
        )

        # Tamper the decision_input snapshot
        for s in trace.steps:
            if s.step == "decision_input" and s.output_snapshot is not None:
                s.output_snapshot["rule_violations"] = [
                    {"rule_id": "FAKE", "rule_type": "forbidden", "risk_level": "high",
                     "description": "injected", "location": ""}
                ]
                break

        # Replay should produce different hash
        replayed = replay_decision(trace)
        assert replayed.decision_hash != pd.decision_hash
