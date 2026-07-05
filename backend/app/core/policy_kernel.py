"""Policy Enforcement Kernel — 系统唯一决策入口

强制执行优先级: HARD_RULE > PLATFORM > TENANT > UX > LLM
每层只能升级(escalate)风险，不能降级(de-escalate)。
每一步生成 hash trace，保证审计可追溯。
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# 结构化策略类型（禁止字符串枚举）
# ═══════════════════════════════════════════════════════════════

class RiskLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DecisionAction(str, Enum):
    BLOCK = "block"
    REQUIRE_REVIEW = "require_review"
    WARN = "warn"
    PASS = "pass"


class PolicySource(str, Enum):
    HARD_RULE = "hard_rule"
    PLATFORM = "platform"
    TENANT = "tenant"
    UX = "ux"
    LLM = "llm"


class TenantPolicy(BaseModel):
    """租户级策略 — 租户自定义风险偏好与规则覆盖"""

    tenant_id: str = "default"
    risk_threshold: RiskLevel = RiskLevel.MEDIUM
    # 该租户抑制的规则 ID：这些规则不触发 block
    suppressed_rule_ids: set[str] = Field(default_factory=set)
    # 自动失败规则类型：这些类型的违规直接 block
    auto_fail_rule_types: set[str] = Field(default_factory=set)
    # LLM 单独发现的风险是否需要人工复核
    requires_human_review_if_llm_only: bool = True
    # 租户自定义行业分类（影响规则激活）
    industries: list[str] = Field(default_factory=list)


class PlatformPolicy(BaseModel):
    """平台级策略 — 公共资源交易平台的特定规则覆盖"""

    platform_id: str = ""
    # 平台特有的阈值覆盖
    threshold_overrides: dict[str, float] = Field(default_factory=dict)
    # 平台强制要求的章节
    required_sections: set[str] = Field(default_factory=set)
    # 平台额外禁止模式
    additional_forbidden_patterns: list[str] = Field(default_factory=list)
    # 平台特定法规引用
    platform_law_refs: list[str] = Field(default_factory=list)


class UxPolicy(BaseModel):
    """UX 策略 — 展示/交互层面的决策"""

    collapse_threshold: int = 3
    hide_risk_levels_below: RiskLevel = RiskLevel.LOW
    group_by: str = "section"


# ═══════════════════════════════════════════════════════════════
# Trace + Decision
# ═══════════════════════════════════════════════════════════════

class TraceStep(BaseModel):
    """单步执行追踪"""
    step: int
    source: PolicySource
    action: DecisionAction
    reason: str
    input_hash: str
    output_hash: str


class PolicyDecision(BaseModel):
    """最终策略决策"""
    final_action: DecisionAction
    final_risk_level: RiskLevel
    requires_human_review: bool
    trace_chain: list[TraceStep] = Field(default_factory=list)
    overrides_applied: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# Decision builder — 避免可变默认参数的 mutable 语义问题
# ═══════════════════════════════════════════════════════════════

class _DecisionBuilder:
    """内部 builder：每层只能升级不能降级"""
    __slots__ = ("action", "risk", "human_review", "overrides")

    def __init__(self, action: DecisionAction, risk: RiskLevel, human_review: bool):
        self.action = action
        self.risk = risk
        self.human_review = human_review
        self.overrides: list[str] = []

    def escalate(self, new_action: DecisionAction, new_risk: RiskLevel,
                 force_review: bool, reason: str, source: PolicySource) -> bool:
        """仅在升级时返回 True"""
        changed = False
        if _action_rank(new_action) > _action_rank(self.action):
            self.action = new_action
            self.overrides.append(f"{source.value}: {reason}")
            changed = True
        if _risk_rank(new_risk) > _risk_rank(self.risk):
            self.risk = new_risk
            self.overrides.append(f"{source.value}: risk {self.risk.value}→{new_risk.value}")
            changed = True
        if force_review and not self.human_review:
            self.human_review = True
            self.overrides.append(f"{source.value}: requires_human_review")
            changed = True
        return changed

    def to_decision(self, trace: list[TraceStep]) -> PolicyDecision:
        return PolicyDecision(
            final_action=self.action,
            final_risk_level=self.risk,
            requires_human_review=self.human_review,
            trace_chain=trace,
            overrides_applied=self.overrides,
        )


def _action_rank(a: DecisionAction) -> int:
    _map = {DecisionAction.PASS: 0, DecisionAction.WARN: 1,
            DecisionAction.REQUIRE_REVIEW: 2, DecisionAction.BLOCK: 3}
    return _map.get(a, 0)


def _risk_rank(r: RiskLevel) -> int:
    _map = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}
    return _map.get(r, 0)


# ═══════════════════════════════════════════════════════════════
# PolicyKernel
# ═══════════════════════════════════════════════════════════════

class PolicyKernel:
    """系统唯一决策入口。

    输入四路结果 + 租户/平台/UX 策略，输出 final_decision + trace_chain。
    强制执行优先级 HARD_RULE > PLATFORM > TENANT > UX > LLM，
    每层只能升级风险，不能降级。
    """

    @staticmethod
    def _hash(*parts: object) -> str:
        """确定性 hash — 相同输入永远产生相同 hash"""
        raw = json.dumps(
            [json.dumps(p, sort_keys=True, default=str, ensure_ascii=False)
             if isinstance(p, dict) else str(p) for p in parts],
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ── 各层策略 ────────────────────────────────────────────

    def _llm_baseline(
        self, llm_result, violations_from_llm: list[dict]
    ) -> tuple[DecisionAction, RiskLevel, bool, str]:
        """第5层 LLM：最底层基线。LLM 单独发现的风险 → warn/review"""
        if not violations_from_llm:
            return DecisionAction.PASS, RiskLevel.LOW, False, "LLM 未发现额外风险"
        has_high = any(v.get("risk_level") == "high" for v in violations_from_llm)
        has_unverified = any(v.get("validation_error") for v in violations_from_llm)
        if has_high:
            return (DecisionAction.REQUIRE_REVIEW, RiskLevel.HIGH, True,
                    f"LLM 发现 {len(violations_from_llm)} 项风险，含 high")
        if has_unverified:
            return (DecisionAction.WARN, RiskLevel.MEDIUM, True,
                    f"LLM 发现 {len(violations_from_llm)} 项待验证风险")
        return (DecisionAction.WARN, RiskLevel.MEDIUM, False,
                f"LLM 发现 {len(violations_from_llm)} 项风险")

    def _apply_ux(
        self, action: DecisionAction, risk: RiskLevel, human_review: bool,
        ux: UxPolicy,
    ) -> tuple[DecisionAction, RiskLevel, bool, str]:
        """第4层 UX：展示策略 — 仅影响展示，不改变风险判定"""
        return (action, risk, human_review,
                f"collapse≥{ux.collapse_threshold} hide≤{ux.hide_risk_levels_below.value}")

    def _apply_tenant(
        self, action: DecisionAction, risk: RiskLevel, human_review: bool,
        tenant: TenantPolicy,
        rule_violations: list[dict], llm_violations: list[dict],
    ) -> tuple[DecisionAction, RiskLevel, bool, str]:
        """第3层 TENANT：租户自定义规则覆盖"""
        reasons: list[str] = []

        # 检查自动失败规则类型
        auto_fail_types = tenant.auto_fail_rule_types
        if auto_fail_types:
            for rv in rule_violations:
                if rv.get("rule_type") in auto_fail_types and rv.get("rule_id") not in tenant.suppressed_rule_ids:
                    return (DecisionAction.BLOCK, RiskLevel.CRITICAL, True,
                            f"租户自动失败规则类型 {rv['rule_type']} 触发: {rv.get('rule_id')}")

        # 抑制规则检查
        suppressed = [rv.get("rule_id") for rv in rule_violations
                      if rv.get("rule_id") in tenant.suppressed_rule_ids]
        if suppressed:
            reasons.append(f"抑制规则 {suppressed}")

        # LLM only 风险 → 人工复核
        if tenant.requires_human_review_if_llm_only and llm_violations and not rule_violations:
            reasons.append("仅 LLM 发现风险，按租户策略需人工复核")
            return (DecisionAction.REQUIRE_REVIEW, risk, True, "; ".join(reasons))

        if not reasons:
            reasons.append("无租户策略覆盖触发")
        return (action, risk, human_review, "; ".join(reasons))

    def _apply_platform(
        self, action: DecisionAction, risk: RiskLevel, human_review: bool,
        platform: PlatformPolicy,
        rule_violations: list[dict],
    ) -> tuple[DecisionAction, RiskLevel, bool, str]:
        """第2层 PLATFORM：平台特定规则覆盖"""
        if not platform.platform_id:
            return (action, risk, human_review, "无平台策略")

        reasons: list[str] = []

        # 平台强制章节检查 — 仅当已有 chapter_required 违规时才触发
        if platform.required_sections:
            chapter_violations = [
                rv for rv in rule_violations
                if rv.get("rule_type") == "chapter_required"
            ]
            if chapter_violations:
                present_sections = {rv.get("location", "") for rv in chapter_violations}
                missing = platform.required_sections - {s for s in present_sections if s}
                if missing:
                    return (DecisionAction.BLOCK, RiskLevel.CRITICAL, True,
                            f"平台 {platform.platform_id} 缺少必需章节: {missing}")

        # 平台额外禁止模式检查
        if platform.additional_forbidden_patterns:
            reasons.append(f"平台 {platform.platform_id} 已加载 {len(platform.additional_forbidden_patterns)} 项额外禁止模式")

        # 平台阈值覆盖
        if platform.threshold_overrides:
            reasons.append(f"阈值覆盖: {list(platform.threshold_overrides.keys())}")

        if not reasons:
            reasons.append(f"平台 {platform.platform_id} 无额外约束")
        return (action, risk, human_review, "; ".join(reasons))

    def _apply_hard_rules(
        self, action: DecisionAction, risk: RiskLevel, human_review: bool,
        rule_violations: list[dict],
    ) -> tuple[DecisionAction, RiskLevel, bool, str]:
        """第1层 HARD_RULE：规则引擎违规 → 最高优先级"""
        if not rule_violations:
            return (action, risk, human_review, "无硬规则违规")

        has_forbidden = any(rv.get("rule_type") == "forbidden" for rv in rule_violations)
        has_high = any(rv.get("risk_level") == "high" for rv in rule_violations)
        has_chapter = any(rv.get("rule_type") == "chapter_required" for rv in rule_violations)

        forbidden_count = sum(1 for rv in rule_violations if rv.get("rule_type") == "forbidden")

        if forbidden_count >= 2:
            return (DecisionAction.BLOCK, RiskLevel.CRITICAL, True,
                    f"多项禁止性违规: {forbidden_count} 项 forbidden")
        if has_forbidden and has_high:
            return (DecisionAction.BLOCK, RiskLevel.HIGH, True,
                    "禁止性违规 + 高风险: 阻止发布")
        if has_forbidden:
            return (DecisionAction.REQUIRE_REVIEW, RiskLevel.HIGH, True,
                    "存在禁止性违规，需人工复核")
        if has_chapter:
            return (DecisionAction.REQUIRE_REVIEW, RiskLevel.MEDIUM, True,
                    "缺少必要章节")
        if has_high:
            return (DecisionAction.WARN, RiskLevel.MEDIUM, True,
                    f"存在 {sum(1 for rv in rule_violations if rv.get('risk_level')=='high')} 项高风险")
        return (action, risk, human_review, f"硬规则违规 {len(rule_violations)} 项，无升级")

    # ── 主入口 ───────────────────────────────────────────────

    def decide(
        self,
        *,
        rule_result=None,        # RuleEngineResult
        llm_result=None,         # LLMEngineResult | None
        tenant_policy: TenantPolicy | None = None,
        platform_policy: PlatformPolicy | None = None,
        ux_policy: UxPolicy | None = None,
    ) -> PolicyDecision:
        """系统唯一决策入口。

        输入四路审查结果 + 策略配置，输出 final_decision + trace_chain。
        每一步生成确定性 hash trace。
        """
        tenant = tenant_policy or TenantPolicy()
        platform = platform_policy or PlatformPolicy()
        ux = ux_policy or UxPolicy()

        # 提取违规数据（保持为 dict 列表，解耦引擎类型）
        rule_violations: list[dict] = [
            {
                "rule_id": v.rule_id, "rule_type": v.rule_type,
                "risk_level": v.risk_level, "description": v.description,
                "location": getattr(v, "location", ""),
            }
            for v in (rule_result.violations if rule_result else [])
        ]
        llm_violations: list[dict] = [
            {
                "type": lv.type, "risk_level": lv.risk_level,
                "reason": getattr(lv, "reason", ""),
                "validation_error": getattr(lv, "validation_error", None),
            }
            for lv in (llm_result.violations if llm_result else [])
        ]

        # 输入 hash
        input_hash = self._hash(rule_violations, llm_violations,
                                tenant.model_dump(), platform.model_dump())

        trace: list[TraceStep] = []
        current_hash = input_hash

        # ── 核心流水线：逐层决策 ───────────────────────────
        # 从最低优先级开始，累积升级

        # L5: LLM baseline
        step5 = 5
        l5_action, l5_risk, l5_review, l5_reason = self._llm_baseline(llm_result, llm_violations)
        l5_hash = self._hash(current_hash, "LLM", l5_action.value, l5_risk.value)
        trace.append(TraceStep(step=5, source=PolicySource.LLM,
                               action=l5_action, reason=l5_reason,
                               input_hash=current_hash, output_hash=l5_hash))
        current_hash = l5_hash

        # 初始化 builder
        dec = _DecisionBuilder(l5_action, l5_risk, l5_review)

        # L4: UX
        l4_action, l4_risk, l4_review, l4_reason = self._apply_ux(
            dec.action, dec.risk, dec.human_review, ux)
        l4_hash = self._hash(current_hash, "UX", l4_action.value, l4_risk.value)
        trace.append(TraceStep(step=4, source=PolicySource.UX,
                               action=l4_action, reason=l4_reason,
                               input_hash=current_hash, output_hash=l4_hash))
        current_hash = l4_hash
        dec.escalate(l4_action, l4_risk, l4_review, l4_reason, PolicySource.UX)

        # L3: TENANT
        l3_action, l3_risk, l3_review, l3_reason = self._apply_tenant(
            dec.action, dec.risk, dec.human_review, tenant,
            rule_violations, llm_violations)
        l3_hash = self._hash(current_hash, "TENANT", l3_action.value, l3_risk.value)
        trace.append(TraceStep(step=3, source=PolicySource.TENANT,
                               action=l3_action, reason=l3_reason,
                               input_hash=current_hash, output_hash=l3_hash))
        current_hash = l3_hash
        dec.escalate(l3_action, l3_risk, l3_review, l3_reason, PolicySource.TENANT)

        # L2: PLATFORM
        l2_action, l2_risk, l2_review, l2_reason = self._apply_platform(
            dec.action, dec.risk, dec.human_review, platform, rule_violations)
        l2_hash = self._hash(current_hash, "PLATFORM", l2_action.value, l2_risk.value)
        trace.append(TraceStep(step=2, source=PolicySource.PLATFORM,
                               action=l2_action, reason=l2_reason,
                               input_hash=current_hash, output_hash=l2_hash))
        current_hash = l2_hash
        dec.escalate(l2_action, l2_risk, l2_review, l2_reason, PolicySource.PLATFORM)

        # L1: HARD_RULE — 最高优先级
        l1_action, l1_risk, l1_review, l1_reason = self._apply_hard_rules(
            dec.action, dec.risk, dec.human_review, rule_violations)
        l1_hash = self._hash(current_hash, "HARD_RULE", l1_action.value, l1_risk.value)
        trace.append(TraceStep(step=1, source=PolicySource.HARD_RULE,
                               action=l1_action, reason=l1_reason,
                               input_hash=current_hash, output_hash=l1_hash))
        dec.escalate(l1_action, l1_risk, l1_review, l1_reason, PolicySource.HARD_RULE)

        return dec.to_decision(trace)


# ═══════════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════════

policy_kernel = PolicyKernel()
