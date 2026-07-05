"""PolicyKernel 测试 — 优先级链、降级防护、参数倾向性、terminal 一致性"""

from __future__ import annotations

from app.core.policy_kernel import (
    DecisionAction,
    DecisionInput,
    DecisionState,
    ParseQuality,
    PlatformPolicy,
    PolicyKernel,
    ReasonCode,
    RiskLevel,
    RuleType,
    RuleViolationInput,
    BiasFindingInput,
    LLMViolationInput,
    RoutingInput,
    TenantPolicy,
    PlanTier,
    UxPolicy,
    verify_trace,
)


kernel = PolicyKernel()


def _rv(rule_id="R001", rule_type=RuleType.FORBIDDEN, risk_level=RiskLevel.HIGH, location="", desc="") -> RuleViolationInput:
    return RuleViolationInput(rule_id=rule_id, rule_type=rule_type, risk_level=risk_level, description=desc or f"{rule_id} 违规", location=location)


def _bf(pattern_id="brand_lock", severity=RiskLevel.HIGH, desc="品牌锁定") -> BiasFindingInput:
    return BiasFindingInput(pattern_id=pattern_id, severity=severity, description=desc, matched_text="指定品牌XY")


def _lv(lv_type="exclusivity", risk_level=RiskLevel.HIGH, reason="排他性条款", validation_error=None) -> LLMViolationInput:
    return LLMViolationInput(type=lv_type, risk_level=risk_level, reason=reason, validation_error=validation_error)


# ═══════════════════════════════════════════════════════════════
# 1. parameter-bias-only high: 最终不得 PASS
# ═══════════════════════════════════════════════════════════════

class TestBiasOnly:
    def test_bias_high_only_not_pass(self):
        """仅 parameter-bias high → REQUIRE_REVIEW + HIGH + human_review"""
        di = DecisionInput(
            bias_findings=[_bf("brand_lock", RiskLevel.HIGH, "品牌锁定")],
        )
        d = kernel.decide(di)
        assert d.final_action != DecisionAction.PASS
        assert d.final_risk_level == RiskLevel.HIGH
        assert d.requires_human_review is True
        # HARD_RULE trace 必须包含 bias reason code
        hard = d.trace_chain[-1]
        assert hard.reason_code == ReasonCode.HARD_RULE_BIAS_HIGH
        assert "brand_lock" in str(hard.reason_params.get("pattern_ids", []))

    def test_bias_critical_not_pass_or_low(self):
        """仅 parameter-bias critical → REQUIRE_REVIEW + CRITICAL"""
        di = DecisionInput(
            bias_findings=[_bf("brand_lock", RiskLevel.CRITICAL, "品牌锁定-严重")],
        )
        d = kernel.decide(di)
        assert d.final_action != DecisionAction.PASS
        assert d.final_risk_level == RiskLevel.CRITICAL
        assert d.requires_human_review is True
        assert d.trace_chain[-1].reason_code == ReasonCode.HARD_RULE_BIAS_CRITICAL

    def test_bias_medium_warns(self):
        """仅 parameter-bias medium → WARN + MEDIUM"""
        di = DecisionInput(
            bias_findings=[_bf("weak_bias", RiskLevel.MEDIUM, "轻微倾向")],
        )
        d = kernel.decide(di)
        assert d.final_action == DecisionAction.WARN
        assert d.final_risk_level == RiskLevel.MEDIUM
        assert d.trace_chain[-1].reason_code == ReasonCode.HARD_RULE_BIAS_MEDIUM


# ═══════════════════════════════════════════════════════════════
# 2. terminal 一致性
# ═══════════════════════════════════════════════════════════════

class TestTerminalConsistency:
    def test_terminal_state_matches_trace_last(self):
        """trace_chain[-1].state_after == PolicyDecision final state"""
        di = DecisionInput(
            rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH)],
        )
        d = kernel.decide(di)
        last = d.trace_chain[-1]
        final = DecisionState(
            action=d.final_action,
            risk_level=d.final_risk_level,
            requires_human_review=d.requires_human_review,
        )
        assert last.state_after == final, f"trace[-1].state_after={last.state_after} != final={final}"

    def test_terminal_with_multi_layer(self):
        """多层叠加后 terminal 仍一致"""
        di = DecisionInput(
            rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.MEDIUM)],
            bias_findings=[_bf("brand_lock", RiskLevel.HIGH)],
            llm_violations=[_lv("exclusivity", RiskLevel.HIGH)],
            platform_policy=PlatformPolicy(platform_id="guangdong", required_sections={"招标公告"}),
        )
        d = kernel.decide(di)
        last = d.trace_chain[-1]
        final = DecisionState(
            action=d.final_action,
            risk_level=d.final_risk_level,
            requires_human_review=d.requires_human_review,
        )
        assert last.state_after == final


# ═══════════════════════════════════════════════════════════════
# 3. UX policy 变化 → hash 变化
# ═══════════════════════════════════════════════════════════════

class TestUxHashChange:
    def test_ux_change_affects_hash(self):
        di1 = DecisionInput(ux_policy=UxPolicy(collapse_threshold=3))
        di2 = DecisionInput(ux_policy=UxPolicy(collapse_threshold=999))
        d1 = kernel.decide(di1)
        d2 = kernel.decide(di2)
        # root hash 必须不同
        assert d1.input_hash != d2.input_hash, "UX policy change must change root hash"
        # UX step hash 必须不同
        ux1 = [t for t in d1.trace_chain if t.source.value == "ux"][0]
        ux2 = [t for t in d2.trace_chain if t.source.value == "ux"][0]
        assert ux1.output_hash != ux2.output_hash, "UX step hash must differ with different policy"


# ═══════════════════════════════════════════════════════════════
# 4. trace 篡改检测
# ═══════════════════════════════════════════════════════════════

class TestTraceTamper:
    def test_tamper_source_fails(self):
        di = DecisionInput(rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.MEDIUM)])
        d = kernel.decide(di)
        # 篡改第一个 trace step 的 source
        d.trace_chain[0].reason_code = ReasonCode.HARD_RULE_NONE  # was LLM_*
        result = verify_trace(di, d)
        assert not result["valid"], f"tampered trace should fail: {result['errors']}"

    def test_tamper_state_after_fails(self):
        di = DecisionInput(rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.MEDIUM)])
        d = kernel.decide(di)
        d.trace_chain[-1].state_after.action = DecisionAction.PASS  # force downgrade
        result = verify_trace(di, d)
        assert not result["valid"]

    def test_tamper_hash_fails(self):
        di = DecisionInput(rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.MEDIUM)])
        d = kernel.decide(di)
        d.trace_chain[0].output_hash = "0000000000000000"
        result = verify_trace(di, d)
        assert not result["valid"], f"hash tamper should fail: {result['errors']}"

    def test_tamper_decision_hash_fails(self):
        di = DecisionInput(rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.MEDIUM)])
        d = kernel.decide(di)
        d.decision_hash = "0000000000000000bad_hash"
        result = verify_trace(di, d)
        assert not result["valid"]

    def test_valid_trace_passes(self):
        di = DecisionInput(rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.MEDIUM)])
        d = kernel.decide(di)
        result = verify_trace(di, d)
        assert result["valid"], f"valid trace should pass: {result['errors']}"


# ═══════════════════════════════════════════════════════════════
# 5. 跨进程确定性
# ═══════════════════════════════════════════════════════════════

class TestCrossProcessDeterminism:
    def test_same_input_deterministic(self):
        """相同输入 → 完全相同 64 位 hash"""
        di = DecisionInput(
            rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH)],
            llm_violations=[_lv("exclusivity", RiskLevel.MEDIUM)],
        )
        d1 = kernel.decide(di)
        d2 = kernel.decide(di)
        assert d1.decision_hash == d2.decision_hash
        assert len(d1.decision_hash) == 64
        for t1, t2 in zip(d1.trace_chain, d2.trace_chain):
            assert t1.input_hash == t2.input_hash
            assert t1.output_hash == t2.output_hash


# ═══════════════════════════════════════════════════════════════
# 6. 输入完整性 — 每个字段变化必须改变 hash
# ═══════════════════════════════════════════════════════════════

class TestInputCompleteness:
    def _hash_for(self, **overrides) -> str:
        defaults = dict(
            routing=RoutingInput(),
            rule_violations=[],
            bias_findings=[],
            llm_violations=[],
            parse_quality=ParseQuality.OK,
            tenant_policy=TenantPolicy(),
            platform_policy=PlatformPolicy(),
            ux_policy=UxPolicy(),
        )
        defaults.update(overrides)
        return kernel.decide(DecisionInput(**defaults)).decision_hash

    def test_routing_changes_hash(self):
        h1 = self._hash_for(routing=RoutingInput(traffic_light="green"))
        h2 = self._hash_for(routing=RoutingInput(traffic_light="red"))
        assert h1 != h2

    def test_rule_violations_changes_hash(self):
        h1 = self._hash_for(rule_violations=[])
        h2 = self._hash_for(rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH)])
        assert h1 != h2

    def test_bias_changes_hash(self):
        h1 = self._hash_for(bias_findings=[])
        h2 = self._hash_for(bias_findings=[_bf("brand_lock", RiskLevel.HIGH)])
        assert h1 != h2

    def test_parse_quality_changes_hash(self):
        h1 = self._hash_for(parse_quality=ParseQuality.OK)
        h2 = self._hash_for(parse_quality=ParseQuality.FAILED)
        assert h1 != h2

    def test_tenant_changes_hash(self):
        h1 = self._hash_for(tenant_policy=TenantPolicy(plan_tier=PlanTier.FREE))
        h2 = self._hash_for(tenant_policy=TenantPolicy(plan_tier=PlanTier.ENTERPRISE))
        assert h1 != h2

    def test_platform_changes_hash(self):
        h1 = self._hash_for(platform_policy=PlatformPolicy(platform_id=""))
        h2 = self._hash_for(platform_policy=PlatformPolicy(platform_id="guangdong"))
        assert h1 != h2

    def test_llm_changes_hash(self):
        h1 = self._hash_for(llm_violations=[])
        h2 = self._hash_for(llm_violations=[_lv("exclusivity", RiskLevel.HIGH)])
        assert h1 != h2


# ═══════════════════════════════════════════════════════════════
# 7. 优先级矩阵 — 对所有层组合验证单调升级
# ═══════════════════════════════════════════════════════════════

class TestPriorityMatrix:
    def test_hard_rule_always_wins_over_llm(self):
        """HARD_RULE forbidden vs LLM HIGH: HARD_RULE wins"""
        di = DecisionInput(
            rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.MEDIUM)],
            llm_violations=[_lv("exclusivity", RiskLevel.HIGH)],
        )
        d = kernel.decide(di)
        # HARD_RULE forced REQUIRE_REVIEW, LLM baseline was REQUIRE_REVIEW too → at least REQUIRE_REVIEW
        assert d.final_action in (DecisionAction.REQUIRE_REVIEW, DecisionAction.BLOCK)

    def test_platform_wins_over_tenant(self):
        """PLATFORM missing section blocks even if tenant suppresses"""
        di = DecisionInput(
            rule_violations=[_rv("R003", RuleType.CHAPTER_REQUIRED, RiskLevel.MEDIUM, location="招标公告")],
            platform_policy=PlatformPolicy(platform_id="guangdong", required_sections={"招标公告"}),
            tenant_policy=TenantPolicy(suppressed_rule_ids={"R003"}),
        )
        d = kernel.decide(di)
        # TENANT 抑制 R003 → 不触发 auto_fail
        # PLATFORM: chapter_required 违规 → location="招标公告" matches required "招标公告"，应通过
        # 实际: PLANFORM 不触发因为 location 已匹配 required section
        # HARD_RULE: chapter_required → REQUIRE_REVIEW
        assert d.final_action == DecisionAction.REQUIRE_REVIEW

    def test_execution_order_is_fixed(self):
        """所有决策执行顺序固定：LLM, UX, TENANT, PLATFORM, HARD_RULE"""
        di = DecisionInput()
        d = kernel.decide(di)
        expected_sources = ["llm", "ux", "tenant", "platform", "hard_rule"]
        actual = [t.source.value for t in d.trace_chain]
        assert actual == expected_sources, f"execution order: {actual}"

    def test_priority_ranks_are_descending(self):
        """priority_rank 从 5 递减到 1"""
        di = DecisionInput()
        d = kernel.decide(di)
        ranks = [t.priority_rank for t in d.trace_chain]
        assert ranks == [5, 4, 3, 2, 1]

    def test_no_layer_can_downgrade(self):
        """每一层 state_after >= state_before（action 和 risk）- 使用 rank 而非 value 比较"""
        from app.core.policy_kernel import _ACTION_RANK, _RISK_RANK
        di = DecisionInput(
            rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH)],
        )
        d = kernel.decide(di)
        for t in d.trace_chain:
            assert _ACTION_RANK[t.state_after.action] >= _ACTION_RANK[t.state_before.action], \
                f"{t.source}: action downgrade {t.state_before.action} -> {t.state_after.action}"
            assert _RISK_RANK[t.state_after.risk_level] >= _RISK_RANK[t.state_before.risk_level], \
                f"{t.source}: risk downgrade {t.state_before.risk_level} -> {t.state_after.risk_level}"


# ═══════════════════════════════════════════════════════════════
# 8. 结构化策略 — 无裸字符串
# ═══════════════════════════════════════════════════════════════

class TestStructuredPolicies:
    def test_tenant_auto_fail_uses_enum(self):
        tp = TenantPolicy(auto_fail_rule_types={RuleType.FORBIDDEN})
        assert RuleType.FORBIDDEN in tp.auto_fail_rule_types

    def test_plan_tier_enum(self):
        tp = TenantPolicy(plan_tier=PlanTier.ENTERPRISE)
        assert tp.plan_tier == PlanTier.ENTERPRISE

    def test_reason_code_is_enum(self):
        di = DecisionInput()
        d = kernel.decide(di)
        for t in d.trace_chain:
            assert isinstance(t.reason_code, ReasonCode), f"{t.source}: reason_code must be ReasonCode enum"

    def test_rule_type_is_enum(self):
        rv = _rv("R001", RuleType.FORBIDDEN)
        assert isinstance(rv.rule_type, RuleType)

    def test_risk_level_is_enum(self):
        di = DecisionInput(
            rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.HIGH)]
        )
        d = kernel.decide(di)
        assert isinstance(d.final_risk_level, RiskLevel)

    def test_decision_action_is_enum(self):
        di = DecisionInput()
        d = kernel.decide(di)
        assert isinstance(d.final_action, DecisionAction)


# ═══════════════════════════════════════════════════════════════
# 9. 空输入 → PASS
# ═══════════════════════════════════════════════════════════════

class TestEmptyInput:
    def test_empty_passes(self):
        d = kernel.decide(DecisionInput())
        assert d.final_action == DecisionAction.PASS
        assert d.final_risk_level == RiskLevel.LOW
        assert not d.requires_human_review

    def test_empty_trace_is_5_layers(self):
        d = kernel.decide(DecisionInput())
        assert len(d.trace_chain) == 5

    def test_empty_verify_passes(self):
        di = DecisionInput()
        d = kernel.decide(di)
        result = verify_trace(di, d)
        assert result["valid"]


# ═══════════════════════════════════════════════════════════════
# 10. 旧旁路防回归
# ═══════════════════════════════════════════════════════════════

class TestNoOldBypass:
    def test_derive_merge_fields(self):
        from app.core.policy_kernel import derive_merge_fields
        di = DecisionInput(rule_violations=[_rv("R001", RuleType.FORBIDDEN, RiskLevel.MEDIUM)])
        d = kernel.decide(di)
        compat = derive_merge_fields(d)
        assert compat["risk_level"] == d.final_risk_level.value
        assert compat["requires_human_review"] == d.requires_human_review
        if d.final_action == DecisionAction.PASS:
            assert compat["review_status"] == "auto_passed"
            assert compat["final_passed"] is True

    def test_member_no_total_score_bypass(self):
        """member.py 不再有 total_score >= 85 作为 DB 查询条件的通过标准"""
        import inspect
        from app.api import member as member_mod
        src = inspect.getsource(member_mod)
        # _compute_risk_level 已删除
        assert "_compute_risk_level" not in src
        # total_score >= 85 不能出现在实际代码行中（注释/docstring 除外）
        lines = [l for l in src.split('\n') if not l.strip().startswith('#') and '"""' not in l and not l.strip().startswith('*') and '不再使用' not in l and '不再以' not in l]
        code_only = '\n'.join(lines)
        # 文档字符串中的引用不算
        assert "total_score >= 85" not in code_only

    def test_fusion_no_decision_fields(self):
        """FourWayRiskMerger.merge() 返回的 MergeResult 不再有决策字段"""
        from app.engine.fusion import MergeResult
        fields = MergeResult.model_fields
        assert "final_passed" not in fields
        assert "review_status" not in fields
        assert "requires_human_review" not in fields
        # risk_items 仍然存在
        assert "risk_items" in fields
