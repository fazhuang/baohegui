"""Trace 完整性测试 — hash 确定性、篡改检测、跨进程确定性"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.core.policy_kernel import (
    DecisionInput,
    DecisionState,
    DecisionAction,
    ParseQuality,
    PlatformPolicy,
    PolicyKernel,
    PolicySource,
    ReasonCode,
    RiskLevel,
    RuleType,
    RuleViolationInput,
    TenantPolicy,
    PlanTier,
    UxPolicy,
    verify_trace,
    sha256_hex,
    _canonical_json,
    TraceStep,
    PolicyDecision,
    POLICY_SCHEMA_VERSION,
)


kernel = PolicyKernel()


def _rv(rule_id="R001", rule_type=RuleType.FORBIDDEN, risk_level=RiskLevel.HIGH) -> RuleViolationInput:
    return RuleViolationInput(rule_id=rule_id, rule_type=rule_type, risk_level=risk_level, description=f"{rule_id} 违规")


class TestTraceIntegrity:
    """trace 内部一致性校验"""

    def test_valid_trace_passes_all_checks(self):
        di = DecisionInput(
            rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.MEDIUM)],
            platform_policy=PlatformPolicy(platform_id="guangdong"),
        )
        d = kernel.decide(di)
        result = verify_trace(di, d)
        assert result["valid"], f"valid trace must pass: {result['errors']}"
        # 所有 checks 为 True
        assert all(v for v in result["checks"].values()), f"some checks failed: {result['checks']}"

    def test_chain_continuity(self):
        """每一步 output_hash == 下一步 input_hash"""
        di = DecisionInput(
            rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH)],
            llm_violations=[],
        )
        d = kernel.decide(di)
        for i in range(1, len(d.trace_chain)):
            assert d.trace_chain[i].input_hash == d.trace_chain[i - 1].output_hash, \
                f"chain broken at step {i}"

    def test_root_hash_matches(self):
        """input_hash == SHA256(canonical_json(DecisionInput))"""
        di = DecisionInput(
            rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH)],
        )
        d = kernel.decide(di)
        expected = sha256_hex(_canonical_json(di))
        assert d.input_hash == expected

    def test_decision_hash_terminal(self):
        """decision_hash 覆盖最终状态"""
        di = DecisionInput(
            rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH)],
        )
        d = kernel.decide(di)
        assert len(d.decision_hash) == 64
        assert d.decision_hash != d.input_hash


class TestHashDeterminism:
    """确定性: 相同输入 → 完全相同输出"""

    def test_deterministic_with_set(self):
        """set 的序列化必须稳定排序"""
        tp1 = TenantPolicy(auto_fail_rule_types={RuleType.FORBIDDEN, RuleType.CHAPTER_REQUIRED})
        tp2 = TenantPolicy(auto_fail_rule_types={RuleType.CHAPTER_REQUIRED, RuleType.FORBIDDEN})  # 不同插入顺序
        di1 = DecisionInput(rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH)], tenant_policy=tp1)
        di2 = DecisionInput(rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH)], tenant_policy=tp2)
        assert di1.tenant_policy.auto_fail_rule_types == di2.tenant_policy.auto_fail_rule_types
        d1 = kernel.decide(di1)
        d2 = kernel.decide(di2)
        assert d1.decision_hash == d2.decision_hash

    def test_deterministic_with_list_order(self):
        """rule_violations 不同顺序 → 可能不同 hash（列表保序）"""
        di1 = DecisionInput(
            rule_violations=[
                _rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH),
                _rv("R002", RuleType.CHAPTER_REQUIRED, RiskLevel.MEDIUM),
            ]
        )
        di2 = DecisionInput(
            rule_violations=[
                _rv("R002", RuleType.CHAPTER_REQUIRED, RiskLevel.MEDIUM),
                _rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH),
            ]
        )
        d1 = kernel.decide(di1)
        d2 = kernel.decide(di2)
        assert d1.decision_hash != d2.decision_hash  # list order matters


class TestCanonicalJson:
    """规范化 JSON 序列化"""

    def test_set_sorted(self):
        data = {"z": 1, "a": 2, "nums": {3, 1, 2}}
        json_bytes = _canonical_json(data)
        text = json_bytes.decode("utf-8")
        # keys sorted
        assert text.index('"a"') < text.index('"nums"') < text.index('"z"')
        # set sorted
        assert "[1,2,3]" in text

    def test_enum_serialized_as_value(self):
        data = {"action": RiskLevel.HIGH}
        json_bytes = _canonical_json(data)
        assert b'"high"' in json_bytes

    def test_no_default_str_repr(self):
        """没有 default=str 产生的 __repr__ 污染"""
        data = {"val": 42}
        json_bytes = _canonical_json(data)
        assert b"__repr__" not in json_bytes
        assert b"<" not in json_bytes


class TestCrossProcessDeterminism:
    """跨进程确定性: 不同 PYTHONHASHSEED → 相同 hash"""

    SCRIPT = """
import json, sys
sys.path.insert(0, {backend!r})
from app.core.policy_kernel import (
    DecisionInput, PolicyKernel, RiskLevel, RuleType, RuleViolationInput,
)
kernel = PolicyKernel()
di = DecisionInput(
    rule_violations=[
        RuleViolationInput(rule_id="R001", rule_type=RuleType.FORBIDDEN, risk_level=RiskLevel.HIGH, description="test"),
        RuleViolationInput(rule_id="R002", rule_type=RuleType.CHAPTER_REQUIRED, risk_level=RiskLevel.MEDIUM, description="test"),
    ],
    bias_findings=[],
    llm_violations=[],
)
d = kernel.decide(di)
print(json.dumps({{
    "decision_hash": d.decision_hash,
    "input_hash": d.input_hash,
    "final_action": d.final_action.value,
}}))
"""

    def test_cross_process_hash_match(self):
        backend = str(Path(__file__).resolve().parent.parent)
        script = self.SCRIPT.format(backend=backend)

        # Run twice with different PYTHONHASHSEED
        env1 = {**__import__("os").environ, "PYTHONHASHSEED": "12345"}
        env2 = {**__import__("os").environ, "PYTHONHASHSEED": "67890"}

        r1 = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env1, cwd=backend)
        r2 = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env2, cwd=backend)

        assert r1.returncode == 0, f"run1 failed: {r1.stderr}"
        assert r2.returncode == 0, f"run2 failed: {r2.stderr}"

        import json as _json
        result1 = _json.loads(r1.stdout.strip())
        result2 = _json.loads(r2.stdout.strip())

        assert result1["decision_hash"] == result2["decision_hash"], \
            f"cross-process hash mismatch: {result1['decision_hash']} != {result2['decision_hash']}"
        assert result1["input_hash"] == result2["input_hash"]


class TestTamperDetection:
    """篡改检测 — verify_trace 必须拒绝任何修改"""

    def _make_decision(self):
        di = DecisionInput(
            rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.MEDIUM)],
        )
        return di, kernel.decide(di)

    def test_tamper_source_value(self):
        di, d = self._make_decision()
        d.trace_chain[0].reason_code = ReasonCode.HARD_RULE_NONE
        assert not verify_trace(di, d)["valid"]

    def test_tamper_state_before(self):
        di, d = self._make_decision()
        d.trace_chain[4].state_before = DecisionState(action=DecisionAction.BLOCK, risk_level=RiskLevel.CRITICAL, requires_human_review=True)
        assert not verify_trace(di, d)["valid"]

    def test_tamper_state_after(self):
        di, d = self._make_decision()
        # Tamper HARD_RULE layer (index 4) — the only non-passthrough layer for this input
        d.trace_chain[4].state_after = DecisionState(action=DecisionAction.PASS, risk_level=RiskLevel.LOW, requires_human_review=False)
        assert not verify_trace(di, d)["valid"]

    def test_tamper_input_hash(self):
        di, d = self._make_decision()
        d.input_hash = "0" * 64
        assert not verify_trace(di, d)["valid"]

    def test_tamper_decision_hash(self):
        di, d = self._make_decision()
        d.decision_hash = "0" * 64
        assert not verify_trace(di, d)["valid"]

    def test_tamper_remove_step(self):
        di, d = self._make_decision()
        d.trace_chain.pop()
        assert not verify_trace(di, d)["valid"]

    def test_tamper_reorder_steps(self):
        di, d = self._make_decision()
        d.trace_chain[0], d.trace_chain[1] = d.trace_chain[1], d.trace_chain[0]
        result = verify_trace(di, d)
        assert not result["valid"], f"reordered trace should fail: {result['errors']}"


class TestSemanticReplay:
    """verify_trace 通过完整语义回放检测伪造"""

    def test_forged_one_step_pass(self):
        """FORBIDDEN/HIGH 输入，手动构造一步 PASS trace → verify_trace 必须失败"""
        di = DecisionInput(
            rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH)],
        )
        real = kernel.decide(di)
        assert real.final_action != DecisionAction.PASS  # real is BLOCK

        from app.core.policy_kernel import (
            _canonical_json, sha256_hex,
            DecisionState, TraceStep, PolicyDecision, POLICY_SCHEMA_VERSION,
        )
        fake_state = DecisionState(action=DecisionAction.PASS, risk_level=RiskLevel.LOW, requires_human_review=False)
        root = sha256_hex(_canonical_json(di))
        event = {
            "schema_version": POLICY_SCHEMA_VERSION, "execution_index": 0, "priority_rank": 1,
            "source": "hard_rule", "state_before": fake_state.model_dump(mode="json"),
            "proposed_transition": fake_state.model_dump(mode="json"),
            "state_after": fake_state.model_dump(mode="json"),
            "reason_code": "hard_rule_passthrough", "reason_params": {},
        }
        step_hash = sha256_hex(root.encode() + _canonical_json(event))
        trace = TraceStep(execution_index=0, priority_rank=1, source=PolicySource.HARD_RULE,
                          reason_code=ReasonCode.HARD_RULE_PASSTHROUGH,
                          state_before=fake_state, proposed_transition=fake_state,
                          state_after=fake_state, input_hash=root, output_hash=step_hash)

        final_data = _canonical_json({"final_action": "pass", "final_risk_level": "low",
                                      "requires_human_review": False, "schema_version": POLICY_SCHEMA_VERSION,
                                      "input_hash": root})
        dec_hash = sha256_hex(step_hash.encode() + final_data)

        fake = PolicyDecision(
            final_action=DecisionAction.PASS, final_risk_level=RiskLevel.LOW,
            requires_human_review=False, input_hash=root, decision_hash=dec_hash,
            trace_chain=[trace], schema_version=POLICY_SCHEMA_VERSION,
        )

        result = verify_trace(di, fake)
        assert not result["valid"], f"forged one-step PASS should fail: {result['errors']}"
        assert result["integrity_status"] != "verified"

    def test_forged_five_step_semantic_mismatch(self):
        """正确 source 序列 + 正确 hash，但篡改 HARD_RULE proposal → 失败"""
        di = DecisionInput(
            rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH)],
        )
        real = kernel.decide(di)
        assert real.final_action == DecisionAction.BLOCK

        fake = real.model_copy(deep=True)
        fake.trace_chain[4].proposed_transition = DecisionState(
            action=DecisionAction.PASS, risk_level=RiskLevel.LOW, requires_human_review=False,
        )

        from app.core.policy_kernel import _canonical_json, sha256_hex
        current = fake.input_hash
        for i, step in enumerate(fake.trace_chain):
            event = {
                "schema_version": fake.schema_version, "execution_index": step.execution_index,
                "priority_rank": step.priority_rank, "source": step.source.value,
                "state_before": step.state_before.model_dump(mode="json"),
                "proposed_transition": step.proposed_transition.model_dump(mode="json"),
                "state_after": step.state_after.model_dump(mode="json"),
                "reason_code": step.reason_code.value, "reason_params": step.reason_params,
            }
            step.input_hash = current
            step.output_hash = sha256_hex(current.encode() + _canonical_json(event))
            current = step.output_hash

        final_data = _canonical_json({
            "final_action": fake.final_action.value, "final_risk_level": fake.final_risk_level.value,
            "requires_human_review": fake.requires_human_review, "schema_version": fake.schema_version,
            "input_hash": fake.input_hash,
        })
        fake.decision_hash = sha256_hex(current.encode() + final_data)

        result = verify_trace(di, fake)
        assert not result["valid"], f"forged semantic mismatch should fail: {result['errors']}"

    def test_missing_source_detected(self):
        """trace 缺层 → semantic replay 失败"""
        di = DecisionInput()
        fake = kernel.decide(di).model_copy(deep=True)
        fake.trace_chain = fake.trace_chain[:3]
        result = verify_trace(di, fake)
        assert not result["valid"]

    def test_repeated_source_detected(self):
        """trace 重复 source → replay 失败"""
        di = DecisionInput()
        fake = kernel.decide(di).model_copy(deep=True)
        fake.trace_chain = fake.trace_chain + [fake.trace_chain[0]]
        result = verify_trace(di, fake)
        assert not result["valid"]

    def test_reordered_source_detected(self):
        """trace source 乱序 → replay 失败"""
        di = DecisionInput()
        fake = kernel.decide(di).model_copy(deep=True)
        fake.trace_chain[0], fake.trace_chain[4] = fake.trace_chain[4], fake.trace_chain[0]
        result = verify_trace(di, fake)
        assert not result["valid"]


# ═══════════════════════════════════════════════════════════════
# Policy Schema Version — 2.0.0 固定制品回放
# ═══════════════════════════════════════════════════════════════

import json as _json_mod
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


class TestV2_0_FixtureReplay:
    """固定 2.0.0 制品在当前代码下验证成功"""

    def _load_fixture(self, name):
        path = FIXTURE_DIR / name
        with open(path, encoding="utf-8") as f:
            return _json_mod.load(f)

    def test_fixture_v2_0_verified(self):
        """固定 2.0.0 制品 → valid True, status verified, hash 与 fixture 完全一致"""
        fx = self._load_fixture("v2_0_0_verified.json")
        assert fx["schema_version"] == "2.0.0"
        assert fx["input_hash"] == fx["_policy_decision"]["input_hash"]

        from app.core.policy_kernel import (
            DecisionInputV2_0, PolicyDecision,
            verify_trace_for_version, _V2_KNOWN,
        )
        di_raw = fx["_decision_input"]
        pd_raw = fx["_policy_decision"]

        # 三端版本一致
        assert di_raw["schema_version"] == "2.0.0"
        assert pd_raw["schema_version"] == "2.0.0"

        # 版本解析成功（no requires_human_review field）
        di = DecisionInputV2_0.model_validate(di_raw)
        pd = PolicyDecision.model_validate(pd_raw)
        assert di.schema_version == "2.0.0"
        assert pd.schema_version == "2.0.0"

        # llm_violations 不含 requires_human_review
        for lv in di.llm_violations:
            assert not hasattr(lv, "requires_human_review")

        # 版本化验证成功
        vr = verify_trace_for_version(di_raw, pd_raw)
        assert vr["valid"], f"verify_trace_for_version failed: {vr['errors']}"
        assert vr["integrity_status"] == "verified"

        # hash 与 fixture 完全一致
        assert pd.input_hash == fx["input_hash"]
        assert pd.decision_hash == fx["decision_hash"]

    def test_v2_0_with_extra_field_fails(self):
        """2.0.0 输入加入 requires_human_review 字段 → parse 失败 (extra='forbid')"""
        fx = self._load_fixture("v2_0_0_verified.json")
        di_raw = fx["_decision_input"].copy()
        # 注入 requires_human_review
        di_raw["llm_violations"] = [dict(lv, requires_human_review=True) for lv in di_raw["llm_violations"]]

        from app.core.policy_kernel import DecisionInputV2_0
        import pytest
        with pytest.raises(Exception):
            DecisionInputV2_0.model_validate(di_raw)

    def test_tampered_hash_fails(self):
        """篡改旧制品 decision_hash → verify_trace_for_version 失败"""
        fx = self._load_fixture("v2_0_0_verified.json")
        pd_raw = fx["_policy_decision"].copy()
        pd_raw["decision_hash"] = "0" * 64

        from app.core.policy_kernel import verify_trace_for_version
        vr = verify_trace_for_version(fx["_decision_input"], pd_raw)
        assert not vr["valid"]

    def test_tampered_input_hash_fails(self):
        """篡改旧制品 input_hash → verify_trace_for_version 失败"""
        fx = self._load_fixture("v2_0_0_verified.json")
        pd_raw = fx["_policy_decision"].copy()
        pd_raw["input_hash"] = "0" * 64

        from app.core.policy_kernel import verify_trace_for_version
        vr = verify_trace_for_version(fx["_decision_input"], pd_raw)
        assert not vr["valid"]

    def test_tampered_trace_fails(self):
        """篡改旧制品 trace → verify_trace_for_version 失败"""
        fx = self._load_fixture("v2_0_0_verified.json")
        pd_raw = _json_mod.loads(_json_mod.dumps(fx["_policy_decision"]))
        if pd_raw.get("trace_chain"):
            pd_raw["trace_chain"][0]["source"] = "hard_rule"

        from app.core.policy_kernel import verify_trace_for_version
        vr = verify_trace_for_version(fx["_decision_input"], pd_raw)
        assert not vr["valid"]

    def test_v2_0_report_passes_verify_report(self):
        """2.0.0 fixture 经 report.py _try_verify_report 返回 verified"""
        fx = self._load_fixture("v2_0_0_verified.json")

        # Simulate a DB report object
        class FakeDBReport:
            decision_integrity_status = "verified"
            policy_schema_version = "2.0.0"
            decision_action = fx["_policy_decision"]["final_action"]
            decision_risk_level = fx["_policy_decision"]["final_risk_level"]
            decision_hash = fx["_policy_decision"]["decision_hash"]
            report_data = _json_mod.dumps({
                "_decision_input": fx["_decision_input"],
                "_policy_decision": fx["_policy_decision"],
            })

        from app.api.report import _try_verify_report
        result = _try_verify_report(FakeDBReport())
        assert result is None, f"expected verified (None), got: {result}"

    def test_v2_0_report_passes_export_gate(self):
        """2.0.0 fixture 通过 verified 导出门禁"""
        fx = self._load_fixture("v2_0_0_verified.json")

        class FakeDBReport:
            decision_integrity_status = "verified"
            policy_schema_version = "2.0.0"
            decision_action = fx["_policy_decision"]["final_action"]
            decision_risk_level = fx["_policy_decision"]["final_risk_level"]
            decision_hash = fx["_policy_decision"]["decision_hash"]
            report_data = _json_mod.dumps({
                "_decision_input": fx["_decision_input"],
                "_policy_decision": fx["_policy_decision"],
            })

        from app.api.report import require_exportable_verified_report
        # Should not raise
        require_exportable_verified_report(FakeDBReport())


class TestVersionMismatch:
    """版本不一致 / 未知版本 → fail-closed"""

    def test_version_mismatch_db_input_decision(self):
        """DB=2.0.0, input=2.1.0, decision=2.1.0 → integrity_failed"""
        class FakeDBReport:
            decision_integrity_status = "verified"
            policy_schema_version = "2.0.0"
            decision_action = "pass"
            decision_risk_level = "low"
            decision_hash = "0" * 64
            report_data = _json_mod.dumps({
                "_decision_input": {"schema_version": "2.1.0", "llm_violations": []},
                "_policy_decision": {"schema_version": "2.1.0", "final_action": "pass",
                                     "final_risk_level": "low", "requires_human_review": False,
                                     "trace_chain": []},
            })

        from app.api.report import _try_verify_report
        result = _try_verify_report(FakeDBReport())
        assert result is not None
        assert result["status"] == "integrity_failed"

    def test_version_mismatch_db_input_decision_2(self):
        """DB=2.1.0, input=2.0.0, decision=2.0.0 → integrity_failed"""
        class FakeDBReport:
            decision_integrity_status = "verified"
            policy_schema_version = "2.1.0"
            decision_action = "pass"
            decision_risk_level = "low"
            decision_hash = "0" * 64
            report_data = _json_mod.dumps({
                "_decision_input": {"schema_version": "2.0.0"},
                "_policy_decision": {"schema_version": "2.0.0", "final_action": "pass",
                                     "final_risk_level": "low", "requires_human_review": False,
                                     "trace_chain": []},
            })

        from app.api.report import _try_verify_report
        result = _try_verify_report(FakeDBReport())
        assert result is not None
        assert result["status"] == "integrity_failed"

    def test_input_decision_version_mismatch(self):
        """input 与 decision 版本不同 → version_mismatch"""
        from app.core.policy_kernel import verify_trace_for_version
        vr = verify_trace_for_version(
            {"schema_version": "2.0.0", "llm_violations": []},
            {"schema_version": "2.1.0", "final_action": "pass",
             "final_risk_level": "low", "requires_human_review": False, "trace_chain": []},
        )
        assert not vr["valid"]
        assert vr["integrity_status"] == "version_mismatch"

    def test_unknown_version_fail_closed(self):
        """未知版本 3.0.0 → unsupported_version"""
        from app.core.policy_kernel import verify_trace_for_version
        for sv in ["2.2.0", "3.0.0", "unknown"]:
            vr = verify_trace_for_version(
                {"schema_version": sv, "llm_violations": []},
                {"schema_version": sv, "final_action": "pass",
                 "final_risk_level": "low", "requires_human_review": False, "trace_chain": []},
            )
            assert not vr["valid"], f"expected fail for {sv}"
            assert vr["integrity_status"] == "unsupported_version", \
                f"expected unsupported_version for {sv}, got {vr['integrity_status']}"

    def test_new_decision_is_v2_1(self):
        """新生成决策 schema_version 必须为 2.1.0"""
        from app.core.policy_kernel import DecisionInput, PolicyKernel
        d = PolicyKernel().decide(DecisionInput())
        assert d.schema_version == "2.1.0"

    def test_v2_1_cross_process_hash_determinism(self):
        """相同 2.1.0 输入 → 跨进程 hash 一致"""
        from app.core.policy_kernel import DecisionInput, LLMViolationInput, TenantPolicy, PlanTier, PolicyKernel, RiskLevel

        def make():
            di = DecisionInput(
                tenant_policy=TenantPolicy(plan_tier=PlanTier.ENTERPRISE,
                                           requires_human_review_if_llm_only=False),
                llm_violations=[LLMViolationInput(type="证据不足", risk_level=RiskLevel.MEDIUM,
                                                  requires_human_review=True)],
            )
            return PolicyKernel().decide(di)

        import subprocess, sys, textwrap
        backend_dir = str(Path(__file__).resolve().parent.parent)
        code = textwrap.dedent("""
            from app.core.policy_kernel import DecisionInput, LLMViolationInput, TenantPolicy, PlanTier, PolicyKernel, RiskLevel
            di = DecisionInput(
                tenant_policy=TenantPolicy(plan_tier=PlanTier.ENTERPRISE, requires_human_review_if_llm_only=False),
                llm_violations=[LLMViolationInput(type="证据不足", risk_level=RiskLevel.MEDIUM, requires_human_review=True)],
            )
            d = PolicyKernel().decide(di)
            print(d.decision_hash)
        """)
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=backend_dir,
        )
        assert r.returncode == 0, f"subprocess failed: {r.stderr}"
        expected_hash = r.stdout.strip()
        assert expected_hash, "subprocess produced empty hash"

        # In-process must match
        d = make()
        assert d.decision_hash == expected_hash, \
            f"cross-process mismatch: in-process={d.decision_hash}, subprocess={expected_hash}"
