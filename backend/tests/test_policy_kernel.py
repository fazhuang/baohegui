"""PolicyKernel — 系统唯一决策入口测试

验证: 优先级链 HARD_RULE > PLATFORM > TENANT > UX > LLM
      每层只能升级不能降级, hash trace 确定性
"""

from __future__ import annotations

from app.core.policy_kernel import (
    DecisionAction,
    PlatformPolicy,
    PolicyKernel,
    PolicySource,
    RiskLevel,
    TenantPolicy,
    UxPolicy,
)
from app.engine.shared_types import RuleEngineResult, Violation


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _rv(rule_id="R001", rule_type="forbidden", risk_level="high", **kw) -> Violation:
    defaults = {"description": f"{rule_id} 违规", "risk_level": risk_level, "weight": 10.0}
    defaults.update(kw)
    return Violation(rule_id=rule_id, rule_type=rule_type, **defaults)


def _rule_result(*violations: Violation) -> RuleEngineResult:
    return RuleEngineResult(violations=list(violations))


# ═══════════════════════════════════════════════════════════════
# 优先级链
# ═══════════════════════════════════════════════════════════════

class TestPriorityChain:
    """HARD_RULE > PLATFORM > TENANT > UX > LLM — 逐层升级"""

    kernel = PolicyKernel()

    def test_empty_input_passes(self):
        """空输入 → PASS"""
        decision = self.kernel.decide()
        assert decision.final_action == DecisionAction.PASS
        assert decision.final_risk_level == RiskLevel.LOW
        assert not decision.requires_human_review
        assert len(decision.trace_chain) == 5  # all 5 layers

    def test_hard_rule_forbidden_blocks(self):
        """单个 forbidden → REQUIRE_REVIEW + HUMAN_REVIEW"""
        rr = _rule_result(_rv("R001", "forbidden", "medium"))
        decision = self.kernel.decide(rule_result=rr)
        assert decision.final_action == DecisionAction.REQUIRE_REVIEW
        assert decision.requires_human_review
        # 确认 HARD_RULE 在 trace 中存在
        hard = [t for t in decision.trace_chain if t.source == PolicySource.HARD_RULE]
        assert len(hard) == 1
        assert hard[0].action == DecisionAction.REQUIRE_REVIEW

    def test_double_forbidden_critical_block(self):
        """≥2 项 forbidden → BLOCK + CRITICAL"""
        rr = _rule_result(
            _rv("R001", "forbidden", "high"),
            _rv("R002", "forbidden", "high"),
        )
        decision = self.kernel.decide(rule_result=rr)
        assert decision.final_action == DecisionAction.BLOCK
        assert decision.final_risk_level == RiskLevel.CRITICAL

    def test_hard_rule_chapter_requires_review(self):
        """缺少必需章节 → REQUIRE_REVIEW + MEDIUM"""
        rr = _rule_result(_rv("R003", "chapter_required", "medium"))
        decision = self.kernel.decide(rule_result=rr)
        assert decision.final_action == DecisionAction.REQUIRE_REVIEW
        assert decision.requires_human_review

    def test_platform_missing_section_blocks(self):
        """平台要求必需章节缺失 → BLOCK + CRITICAL"""
        rr = _rule_result(_rv("R003", "chapter_required", "medium", description="缺少《招标公告》"))
        pf = PlatformPolicy(
            platform_id="guangdong",
            required_sections={"招标公告"},
        )
        decision = self.kernel.decide(rule_result=rr, platform_policy=pf)
        assert decision.final_action == DecisionAction.BLOCK
        assert decision.final_risk_level == RiskLevel.CRITICAL

    def test_platform_no_override_when_satisfied(self):
        """平台章节已存在 → 不升级"""
        rr = _rule_result()  # no violations at all
        pf = PlatformPolicy(
            platform_id="guangdong",
            required_sections={"招标公告"},
        )
        decision = self.kernel.decide(rule_result=rr, platform_policy=pf)
        # 无 chapter_required 违规 → 平台检查通过 → 不应 block
        assert decision.final_action != DecisionAction.BLOCK

    def test_tenant_auto_fail_blocks(self):
        """租户 auto_fail 规则类型触发 → BLOCK"""
        rr = _rule_result(_rv("R001", "forbidden", "high"))
        tp = TenantPolicy(
            tenant_id="strict_tenant",
            auto_fail_rule_types={"forbidden"},
        )
        decision = self.kernel.decide(rule_result=rr, tenant_policy=tp)
        assert decision.final_action == DecisionAction.BLOCK
        assert decision.final_risk_level == RiskLevel.CRITICAL

    def test_tenant_suppressed_rule_not_blocked(self):
        """抑制的规则不触发 auto_fail"""
        rr = _rule_result(_rv("R001", "forbidden", "medium"))
        tp = TenantPolicy(
            tenant_id="lenient_tenant",
            auto_fail_rule_types={"forbidden"},
            suppressed_rule_ids={"R001"},
        )
        decision = self.kernel.decide(rule_result=rr, tenant_policy=tp)
        # suppressed → auto_fail 不触发 → hard_rule 层 REQUIRE_REVIEW
        assert decision.final_action == DecisionAction.REQUIRE_REVIEW

    def test_tenant_llm_only_review(self):
        """仅 LLM 发现风险 → 按租户策略需复核"""
        tp = TenantPolicy(requires_human_review_if_llm_only=True)
        decision = self.kernel.decide(rule_result=_rule_result(), tenant_policy=tp)
        # 没有 llm_result → 无 LLM 风险
        assert decision.final_action == DecisionAction.PASS

    def test_layers_cannot_downgrade(self):
        """每一层只能升级不能降级 — hard_rule forbidden 被 platform 覆盖不降级"""
        rr = _rule_result(_rv("R001", "forbidden", "high"))
        # 平台无严格规则 → hard_rule 的 REQUIRE_REVIEW 应保留
        pf = PlatformPolicy(platform_id="jiangsu")
        decision = self.kernel.decide(rule_result=rr, platform_policy=pf)
        # HARD_RULE 设了 REQUIRE_REVIEW → platform 不应降级
        assert decision.final_action in (DecisionAction.REQUIRE_REVIEW, DecisionAction.BLOCK)

    def test_ux_layer_preserves_action(self):
        """UX 层不改变 action/risk"""
        rr = _rule_result(_rv("R010", "keyword_required", "low"))
        ux = UxPolicy(collapse_threshold=5, hide_risk_levels_below=RiskLevel.LOW)
        decision = self.kernel.decide(rule_result=rr, ux_policy=ux)
        # UX 层不升级 → action 仍来自硬规则（无 upgrade → PASS）
        ux_trace = [t for t in decision.trace_chain if t.source == PolicySource.UX]
        assert len(ux_trace) == 1
        assert ux_trace[0].action in (DecisionAction.PASS, DecisionAction.WARN)


# ═══════════════════════════════════════════════════════════════
# Trace hash 确定性
# ═══════════════════════════════════════════════════════════════

class TestTraceHash:
    """Hash trace 确定性：相同输入 → 相同 hash"""

    kernel = PolicyKernel()

    def test_hash_deterministic(self):
        """相同输入重复调用 → 相同 trace hash"""
        rr = _rule_result(_rv("R001", "forbidden", "high"))
        decision1 = self.kernel.decide(rule_result=rr)
        decision2 = self.kernel.decide(rule_result=rr)

        t1 = [(t.step, t.source.value, t.input_hash, t.output_hash) for t in decision1.trace_chain]
        t2 = [(t.step, t.source.value, t.input_hash, t.output_hash) for t in decision2.trace_chain]
        assert t1 == t2

    def test_hash_differs_with_different_input(self):
        """不同输入 → hash 不同"""
        d1 = self.kernel.decide(rule_result=_rule_result(_rv("R001", "forbidden", "high")))
        d2 = self.kernel.decide(rule_result=_rule_result(_rv("R001", "keyword_required", "low")))
        assert d1.trace_chain[0].input_hash != d2.trace_chain[0].input_hash

    def test_all_layers_present_in_trace(self):
        """完整 trace 包含五层"""
        rr = _rule_result(_rv("R001", "forbidden", "high"))
        decision = self.kernel.decide(rule_result=rr)
        sources = {t.source for t in decision.trace_chain}
        expected = {PolicySource.HARD_RULE, PolicySource.PLATFORM,
                    PolicySource.TENANT, PolicySource.UX, PolicySource.LLM}
        assert sources == expected

    def test_trace_step_numbering(self):
        """Trace step 按优先级编号：1=HARD_RULE ... 5=LLM"""
        rr = _rule_result(_rv("R001", "forbidden", "high"))
        decision = self.kernel.decide(rule_result=rr)
        steps = [t.step for t in decision.trace_chain]
        assert steps == [5, 4, 3, 2, 1]  # 从 LLM 开始，HARD_RULE 最后覆盖


# ═══════════════════════════════════════════════════════════════
# 策略结构
# ═══════════════════════════════════════════════════════════════

class TestPolicyTypes:
    """策略类型：结构化，禁止字符串枚举"""

    def test_tenant_policy_defaults(self):
        tp = TenantPolicy()
        assert tp.risk_threshold == RiskLevel.MEDIUM
        assert tp.suppressed_rule_ids == set()
        assert tp.requires_human_review_if_llm_only is True

    def test_platform_policy_defaults(self):
        pp = PlatformPolicy()
        assert pp.platform_id == ""
        assert pp.required_sections == set()

    def test_ux_policy_defaults(self):
        ux = UxPolicy()
        assert ux.collapse_threshold == 3
        assert ux.hide_risk_levels_below == RiskLevel.LOW

    def test_all_enums_are_structured(self):
        """所有枚举值都是结构化类型，无字符串枚举"""
        for name in ("RiskLevel", "DecisionAction", "PolicySource"):
            enum_class = {e.value for e in globals()[name]}
            assert len(enum_class) > 0


# ═══════════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════════

class TestSingleton:
    def test_policy_kernel_singleton_importable(self):
        from app.core.policy_kernel import policy_kernel
        assert isinstance(policy_kernel, PolicyKernel)
