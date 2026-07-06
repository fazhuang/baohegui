"""Policy Enforcement Kernel — 系统唯一决策入口

强制执行优先级: HARD_RULE > PLATFORM > TENANT > UX > LLM
每层只能升级（escalate），不能降级（de-escalate）。

输入: DecisionInput（规范化证据 + 结构化策略）
输出: PolicyDecision（final_action + final_risk_level + trace_chain + decision_hash）

不变量:
- 任何改变 final_action、risk_level、review_status、requires_human_review
  的逻辑只能存在于 PolicyKernel 内部。
- trace_chain[-1].state_after == PolicyDecision final state
- 确定性: 相同 DecisionInput → 相同 PolicyDecision（含 hash）
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# 结构化策略类型 — 零裸字符串
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


class RuleType(str, Enum):
    """规则类型 — 用于策略分支，禁止裸 'forbidden' 字符串"""
    FORBIDDEN = "forbidden"
    CHAPTER_REQUIRED = "chapter_required"
    KEYWORD_REQUIRED = "keyword_required"
    FORMAT_REQUIRED = "format_required"


class PlanTier(str, Enum):
    """订阅计划层级 — 禁止裸 'enterprise' 字符串"""
    ENTERPRISE = "enterprise"
    PRO = "pro"
    FREE = "free"


class ReasonCode(str, Enum):
    """结构化原因码 — 每层决策必须使用，禁止裸原因字符串"""
    # LLM
    LLM_NO_ISSUES = "llm_no_issues"
    LLM_HIGH_RISK = "llm_high_risk"
    LLM_UNVERIFIED = "llm_unverified"
    LLM_REQUIRES_HUMAN_REVIEW = "llm_requires_human_review"
    # UX — 仅展示，不改变判定
    UX_PASSTHROUGH = "ux_passthrough"
    # TENANT
    TENANT_AUTO_FAIL = "tenant_auto_fail"
    TENANT_SUPPRESSED = "tenant_suppressed"
    TENANT_LLM_ONLY_REVIEW = "tenant_llm_only_review"
    TENANT_PASSTHROUGH = "tenant_passthrough"
    # PLATFORM
    PLATFORM_NO_POLICY = "platform_no_policy"
    PLATFORM_MISSING_SECTION = "platform_missing_section"
    PLATFORM_PASSTHROUGH = "platform_passthrough"
    # HARD_RULE — bias findings are determined by parameter analysis, not legal rules
    HARD_RULE_NONE = "hard_rule_none"
    HARD_RULE_MULTI_FORBIDDEN = "hard_rule_multi_forbidden"
    HARD_RULE_FORBIDDEN_HIGH = "hard_rule_forbidden_high"
    HARD_RULE_FORBIDDEN = "hard_rule_forbidden"
    HARD_RULE_MISSING_CHAPTER = "hard_rule_missing_chapter"
    HARD_RULE_HIGH = "hard_rule_high"
    HARD_RULE_BIAS_CRITICAL = "hard_rule_bias_critical"
    HARD_RULE_BIAS_HIGH = "hard_rule_bias_high"
    HARD_RULE_BIAS_MEDIUM = "hard_rule_bias_medium"
    HARD_RULE_PASSTHROUGH = "hard_rule_passthrough"


# ═══════════════════════════════════════════════════════════════
# 单一优先级表（禁止重复定义）
# ═══════════════════════════════════════════════════════════════

_PRIORITY_ORDER: tuple[PolicySource, ...] = (
    PolicySource.LLM,        # priority=5, execution_index=0
    PolicySource.UX,         # priority=4, execution_index=1
    PolicySource.TENANT,     # priority=3, execution_index=2
    PolicySource.PLATFORM,   # priority=2, execution_index=3
    PolicySource.HARD_RULE,  # priority=1, execution_index=4
)

_PRIORITY_RANK: dict[PolicySource, int] = {
    src: len(_PRIORITY_ORDER) - i
    for i, src in enumerate(_PRIORITY_ORDER)
}

_ACTION_RANK: dict[DecisionAction, int] = {
    DecisionAction.PASS: 0,
    DecisionAction.WARN: 1,
    DecisionAction.REQUIRE_REVIEW: 2,
    DecisionAction.BLOCK: 3,
}

_RISK_RANK: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


def _max_action(a: DecisionAction, b: DecisionAction) -> DecisionAction:
    return a if _ACTION_RANK.get(a, 0) >= _ACTION_RANK.get(b, 0) else b


def _max_risk(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    return a if _RISK_RANK.get(a, 0) >= _RISK_RANK.get(b, 0) else b


# ═══════════════════════════════════════════════════════════════
# 共享输入模型 — 所有版本共用

class RuleViolationInput(BaseModel):
    """单条规则引擎违规"""
    rule_id: str = ""
    rule_type: RuleType = RuleType.FORBIDDEN
    risk_level: RiskLevel = RiskLevel.MEDIUM
    description: str = ""
    location: str = ""


class BiasFindingInput(BaseModel):
    """单条参数倾向性发现"""
    pattern_id: str = ""
    severity: RiskLevel = RiskLevel.MEDIUM
    description: str = ""
    matched_text: str = ""
    matched_field: str = ""


class TrafficLight(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class RoutingInput(BaseModel):
    """路由审查结果"""
    traffic_light: TrafficLight = TrafficLight.GREEN
    skip_llm: bool = False


class ParseQuality(str, Enum):
    OK = "ok"
    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    PARTIAL = "partial"
    FAILED = "failed"


# ═══════════════════════════════════════════════════════════════
# 策略类型
# ═══════════════════════════════════════════════════════════════

class TenantPolicy(BaseModel):
    """租户级策略"""
    tenant_id: str = "default"
    # 直接 block 的规则类型
    auto_fail_rule_types: set[RuleType] = Field(default_factory=set)
    # 不触发 block 的规则 ID（精确豁免）
    suppressed_rule_ids: set[str] = Field(default_factory=set)
    # LLM 单独发现的风险是否需要人工复核
    requires_human_review_if_llm_only: bool = True
    # 订阅层级
    plan_tier: PlanTier = PlanTier.FREE


    def model_dump(self, **kwargs) -> dict[str, Any]:
        d = super().model_dump(**kwargs)
        # 确保 set 字段稳定排序（model_dump 将 set 转 list，顺序依赖 hash seed）
        if "auto_fail_rule_types" in d and isinstance(d["auto_fail_rule_types"], list):
            d["auto_fail_rule_types"] = sorted(d["auto_fail_rule_types"])
        if "suppressed_rule_ids" in d and isinstance(d["suppressed_rule_ids"], list):
            d["suppressed_rule_ids"] = sorted(d["suppressed_rule_ids"])
        if "industries" in d and isinstance(d["industries"], list):
            d["industries"] = sorted(d["industries"])
        return d


class PlatformPolicy(BaseModel):
    """平台级策略"""
    platform_id: str = ""
    # 平台强制要求的章节
    required_sections: set[str] = Field(default_factory=set)


class UxPolicy(BaseModel):
    """UX 策略 — 仅影响展示，不改变判定"""
    collapse_threshold: int = 3
    hide_risk_levels_below: RiskLevel = RiskLevel.LOW


# ═══════════════════════════════════════════════════════════════
# Policy Schema Version — 一经发布不可变
# ═══════════════════════════════════════════════════════════════

class PolicySchemaVersion(str, Enum):
    """结构化版本标识 — 禁止使用裸字符串 startswith 放行"""
    V2_0_0 = "2.0.0"
    V2_1_0 = "2.1.0"


POLICY_SCHEMA_VERSION = PolicySchemaVersion.V2_1_0.value  # 当前活跃 schema

# ── v2.0.0 frozen input models（hash schema 不可变）──

class LLMViolationInputV2_0(BaseModel, extra="forbid"):
    """LLM 违规 — v2.0.0 无 requires_human_review 字段"""
    type: str = ""
    risk_level: RiskLevel = RiskLevel.MEDIUM
    reason: str = ""
    validation_error: Optional[str] = None


class DecisionInputV2_0(BaseModel, extra="forbid"):
    """v2.0.0 决策输入 — frozen schema，禁止额外字段"""
    schema_version: Literal["2.0.0"] = "2.0.0"

    routing: RoutingInput = Field(default_factory=RoutingInput)
    rule_violations: list[RuleViolationInput] = Field(default_factory=list)
    bias_findings: list[BiasFindingInput] = Field(default_factory=list)
    llm_violations: list[LLMViolationInputV2_0] = Field(default_factory=list)
    parse_quality: ParseQuality = ParseQuality.OK
    present_sections: set[str] = Field(default_factory=set)

    tenant_policy: TenantPolicy = Field(default_factory=TenantPolicy)
    platform_policy: PlatformPolicy = Field(default_factory=PlatformPolicy)
    ux_policy: UxPolicy = Field(default_factory=UxPolicy)


# ── 当前活跃模型 (2.1.0) ──

# RuleViolationInput / BiasFindingInput / RoutingInput / ParseQuality 见上方共享定义

class LLMViolationInput(BaseModel):
    """单条 LLM 违规 — v2.1.0 含 requires_human_review"""
    type: str = ""
    risk_level: RiskLevel = RiskLevel.MEDIUM
    reason: str = ""
    validation_error: Optional[str] = None
    requires_human_review: bool = False


class DecisionInput(BaseModel):
    """系统唯一决策输入 — 所有影响决策的字段必须在此"""
    schema_version: Literal["2.1.0"] = "2.1.0"

    # 证据
    routing: RoutingInput = Field(default_factory=RoutingInput)
    rule_violations: list[RuleViolationInput] = Field(default_factory=list)
    bias_findings: list[BiasFindingInput] = Field(default_factory=list)
    llm_violations: list[LLMViolationInput] = Field(default_factory=list)
    parse_quality: ParseQuality = ParseQuality.OK
    # 文档真实章节集合（经规范化），用于平台策略等层比对
    present_sections: set[str] = Field(default_factory=set)

    # 策略
    tenant_policy: TenantPolicy = Field(default_factory=TenantPolicy)
    platform_policy: PlatformPolicy = Field(default_factory=PlatformPolicy)
    ux_policy: UxPolicy = Field(default_factory=UxPolicy)


# ═══════════════════════════════════════════════════════════════
# Trace + Decision
# ═══════════════════════════════════════════════════════════════

class DecisionState(BaseModel):
    """一个策略层执行后的累积状态"""
    action: DecisionAction
    risk_level: RiskLevel
    requires_human_review: bool


class TraceStep(BaseModel):
    """单步执行追踪 — state_after 是本层升级后的真实状态"""
    execution_index: int  # 0-based 执行顺序
    priority_rank: int    # 1=HARD_RULE ... 5=LLM
    source: PolicySource
    reason_code: ReasonCode
    reason_params: dict[str, Any] = Field(default_factory=dict)
    state_before: DecisionState
    proposed_transition: DecisionState  # 本层提案
    state_after: DecisionState          # 升级后真实状态
    input_hash: str = ""
    output_hash: str = ""


class PolicyDecision(BaseModel):
    """系统唯一决策输出"""
    final_action: DecisionAction
    final_risk_level: RiskLevel
    requires_human_review: bool
    schema_version: str = POLICY_SCHEMA_VERSION
    input_hash: str = ""
    decision_hash: str = ""
    trace_chain: list[TraceStep] = Field(default_factory=list)
    overrides_applied: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 规范化 JSON — 跨进程确定性
# ═══════════════════════════════════════════════════════════════

def _canonical_json(obj: Any) -> bytes:
    """规范化 JSON 序列化: UTF-8, sorted keys, compact separators, no default=str"""
    return json.dumps(
        _for_json(obj),
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")


def _for_json(obj: Any) -> Any:
    """递归转换对象为 JSON 可序列化，type-directed，不使用 default=str。

    关键不变量：set 转 list 必须稳定排序（跨 PYTHONHASHSEED 一致）。
    """
    _SET_FIELDS = {"auto_fail_rule_types", "suppressed_rule_ids",
                   "industries", "required_sections", "present_sections"}

    if isinstance(obj, Enum):
        return obj.value
    elif isinstance(obj, dict):
        result = {}
        for k, v in sorted(obj.items()):
            val = _for_json(v)
            # 稳定 set 派生字段：任意嵌套层次都生效
            if k in _SET_FIELDS and isinstance(val, list):
                val = sorted(val)
            result[k] = val
        return result
    elif isinstance(obj, set):
        return sorted(_for_json(item) for item in obj)
    elif isinstance(obj, (list, tuple)):
        return [_for_json(item) for item in obj]
    elif isinstance(obj, BaseModel):
        return _for_json(obj.model_dump(mode="json"))
    elif isinstance(obj, bytes):
        return obj.hex()
    elif obj is None:
        return None
    elif isinstance(obj, (int, float, str, bool)):
        return obj
    else:
        return str(obj)


def sha256_hex(data: bytes) -> str:
    """完整 64 位 SHA-256 hex"""
    return hashlib.sha256(data).hexdigest()


# ═══════════════════════════════════════════════════════════════
# PolicyKernel — 唯一决策入口
# ═══════════════════════════════════════════════════════════════

class PolicyKernel:
    """系统唯一决策入口。

    输入 DecisionInputV2_0 | DecisionInput，输出 PolicyDecision。
    强制执行优先级 HARD_RULE > PLATFORM > TENANT > UX > LLM。
    每层只能升级，不能降级。

    trace_chain[-1].state_after == PolicyDecision final state（刚性不变量）

    版本路由由 Pydantic Literal 强约束：
    - DecisionInputV2_0 (Literal["2.0.0"]) → _eval_llm_v2_0（旧 LLM 语义，3 分支）
    - DecisionInput (Literal["2.1.0"]) → _eval_llm_v2_1（新 LLM 语义，4 分支含 requires_human_review）
    - 其他类型 → TypeError / ValueError fail-closed
    """

    def decide(self, decision_input: DecisionInput | DecisionInputV2_0) -> PolicyDecision:
        """单一公开决策入口 — 根据输入模型类型分派 evaluator。"""
        if isinstance(decision_input, DecisionInputV2_0):
            return self._decide_core(decision_input, eval_llm=self._eval_llm_v2_0)
        if isinstance(decision_input, DecisionInput):
            return self._decide_core(decision_input, eval_llm=self._eval_llm_v2_1)
        raise TypeError(f"Unsupported decision input type: {type(decision_input).__name__}")

    def _decide_core(self, di, *, eval_llm) -> PolicyDecision:
        """共享决策执行链 — 版本化 LLM evaluator 通过参数注入"""
        root_hash = sha256_hex(_canonical_json(di))

        trace: list[TraceStep] = []
        pre_hash = root_hash

        # 初始状态: 最低风险基线
        state = DecisionState(
            action=DecisionAction.PASS,
            risk_level=RiskLevel.LOW,
            requires_human_review=False,
        )

        # 按执行顺序逐层（LLM → UX → TENANT → PLATFORM → HARD_RULE）
        for exec_idx, source in enumerate(_PRIORITY_ORDER):
            priority = _PRIORITY_RANK[source]
            state_before = state.model_copy(deep=True)

            proposed, code, params = self._evaluate_layer(source, di, state, eval_llm=eval_llm)

            # 升级规则：只能向更严格的方向
            new_action = _max_action(state.action, proposed.action)
            new_risk = _max_risk(state.risk_level, proposed.risk_level)
            new_hr = state.requires_human_review or proposed.requires_human_review

            state = DecisionState(
                action=new_action,
                risk_level=new_risk,
                requires_human_review=new_hr,
            )

            # 构建 event hash
            event = {
                "schema_version": di.schema_version,
                "execution_index": exec_idx,
                "priority_rank": priority,
                "source": source.value,
                "state_before": state_before.model_dump(mode="json"),
                "proposed_transition": proposed.model_dump(mode="json"),
                "state_after": state.model_dump(mode="json"),
                "reason_code": code.value,
                "reason_params": params,
            }
            event_bytes = _canonical_json(event)
            output_hash = sha256_hex(pre_hash.encode() + event_bytes)

            trace.append(TraceStep(
                execution_index=exec_idx,
                priority_rank=priority,
                source=source,
                reason_code=code,
                reason_params=params,
                state_before=state_before,
                proposed_transition=proposed,
                state_after=state.model_copy(deep=True),
                input_hash=pre_hash,
                output_hash=output_hash,
            ))
            pre_hash = output_hash

        # 终端一致性不变量: trace[-1].state_after == final state
        # （已由上面的循环保证）

        overrides = [
            f"{t.source.value}: {t.reason_code.value}"
            for t in trace
            if t.state_after != t.state_before
        ]

        # 构建最终决策（不含 hash）
        final = PolicyDecision(
            final_action=state.action,
            final_risk_level=state.risk_level,
            requires_human_review=state.requires_human_review,
            schema_version=di.schema_version,
            input_hash=root_hash,
            trace_chain=trace,
            overrides_applied=overrides,
        )

        # decision_hash = SHA256(terminal_output_hash || canonical final without hash)
        final_data = _canonical_json({
            "final_action": final.final_action.value,
            "final_risk_level": final.final_risk_level.value,
            "requires_human_review": final.requires_human_review,
            "schema_version": final.schema_version,
            "input_hash": final.input_hash,
        })
        final.decision_hash = sha256_hex(pre_hash.encode() + final_data)

        return final

    # ── 各层评估 ────────────────────────────────────────────

    def _evaluate_layer(
        self, source: PolicySource, di, current: DecisionState,
        eval_llm,
    ) -> tuple[DecisionState, ReasonCode, dict[str, Any]]:
        """评估单层策略，返回 (提案, 原因码, 原因参数)"""
        handlers = {
            PolicySource.LLM: lambda di, cur: eval_llm(di, cur),
            PolicySource.UX: self._eval_ux,
            PolicySource.TENANT: self._eval_tenant,
            PolicySource.PLATFORM: self._eval_platform,
            PolicySource.HARD_RULE: self._eval_hard_rule,
        }
        return handlers[source](di, current)

    # ── LLM evaluators — 版本化 ──────────────────────────

    def _eval_llm_v2_0(
        self, di, _current: DecisionState,
    ) -> tuple[DecisionState, ReasonCode, dict]:
        """v2.0.0 LLM 评估：3 分支（无 requires_human_review）"""
        if not di.llm_violations:
            return (
                DecisionState(action=DecisionAction.PASS, risk_level=RiskLevel.LOW, requires_human_review=False),
                ReasonCode.LLM_NO_ISSUES, {},
            )
        has_high = any(v.risk_level == RiskLevel.HIGH for v in di.llm_violations)
        has_unverified = any(v.validation_error for v in di.llm_violations)
        if has_high:
            return (
                DecisionState(action=DecisionAction.REQUIRE_REVIEW, risk_level=RiskLevel.HIGH, requires_human_review=True),
                ReasonCode.LLM_HIGH_RISK, {"count": len(di.llm_violations)},
            )
        if has_unverified:
            return (
                DecisionState(action=DecisionAction.WARN, risk_level=RiskLevel.MEDIUM, requires_human_review=True),
                ReasonCode.LLM_UNVERIFIED, {"count": len(di.llm_violations)},
            )
        return (
            DecisionState(action=DecisionAction.WARN, risk_level=RiskLevel.MEDIUM, requires_human_review=False),
            ReasonCode.LLM_HIGH_RISK, {"count": len(di.llm_violations)},
        )

    def _eval_llm_v2_1(
        self, di: DecisionInput, _current: DecisionState,
    ) -> tuple[DecisionState, ReasonCode, dict]:
        """v2.1.0 LLM 评估：4 分支（含 requires_human_review）"""
        if not di.llm_violations:
            return (
                DecisionState(action=DecisionAction.PASS, risk_level=RiskLevel.LOW, requires_human_review=False),
                ReasonCode.LLM_NO_ISSUES, {},
            )
        has_high = any(v.risk_level == RiskLevel.HIGH for v in di.llm_violations)
        has_unverified = any(v.validation_error for v in di.llm_violations)
        has_explicit_review = any(getattr(v, "requires_human_review", False) for v in di.llm_violations)

        # 1. high risk → REQUIRE_REVIEW + HIGH + human_review
        if has_high:
            return (
                DecisionState(action=DecisionAction.REQUIRE_REVIEW, risk_level=RiskLevel.HIGH, requires_human_review=True),
                ReasonCode.LLM_HIGH_RISK, {"count": len(di.llm_violations)},
            )
        # 2. validation_error → WARN + MEDIUM + human_review
        if has_unverified:
            return (
                DecisionState(action=DecisionAction.WARN, risk_level=RiskLevel.MEDIUM, requires_human_review=True),
                ReasonCode.LLM_UNVERIFIED, {"count": len(di.llm_violations)},
            )
        # 3. explicit requires_human_review → WARN + MEDIUM + human_review
        if has_explicit_review:
            return (
                DecisionState(action=DecisionAction.WARN, risk_level=RiskLevel.MEDIUM, requires_human_review=True),
                ReasonCode.LLM_REQUIRES_HUMAN_REVIEW, {"count": len(di.llm_violations)},
            )
        # 4. other medium/low risk → compatible legacy behavior
        return (
            DecisionState(action=DecisionAction.WARN, risk_level=RiskLevel.MEDIUM, requires_human_review=False),
            ReasonCode.LLM_HIGH_RISK, {"count": len(di.llm_violations)},
        )

    def _eval_ux(
        self, di: DecisionInput, current: DecisionState,
    ) -> tuple[DecisionState, ReasonCode, dict]:
        # UX 不改变决策
        return (
            current.model_copy(deep=True),
            ReasonCode.UX_PASSTHROUGH,
            {"collapse_threshold": di.ux_policy.collapse_threshold},
        )

    def _eval_tenant(
        self, di: DecisionInput, current: DecisionState,
    ) -> tuple[DecisionState, ReasonCode, dict]:
        tp = di.tenant_policy

        # auto_fail 检查
        if tp.auto_fail_rule_types:
            for rv in di.rule_violations:
                if rv.rule_type in tp.auto_fail_rule_types and rv.rule_id not in tp.suppressed_rule_ids:
                    return (
                        DecisionState(action=DecisionAction.BLOCK, risk_level=RiskLevel.CRITICAL, requires_human_review=True),
                        ReasonCode.TENANT_AUTO_FAIL,
                        {"rule_type": rv.rule_type.value, "rule_id": rv.rule_id},
                    )

        # 抑制检查
        suppressed = [rv.rule_id for rv in di.rule_violations if rv.rule_id in tp.suppressed_rule_ids]

        # LLM only 风险
        if tp.requires_human_review_if_llm_only and di.llm_violations and not di.rule_violations:
            return (
                DecisionState(action=DecisionAction.REQUIRE_REVIEW, risk_level=current.risk_level, requires_human_review=True),
                ReasonCode.TENANT_LLM_ONLY_REVIEW, {"suppressed": suppressed},
            )

        if suppressed:
            return (
                current.model_copy(deep=True),
                ReasonCode.TENANT_SUPPRESSED, {"suppressed": suppressed},
            )

        return (
            current.model_copy(deep=True),
            ReasonCode.TENANT_PASSTHROUGH, {},
        )

    def _eval_platform(
        self, di: DecisionInput, current: DecisionState,
    ) -> tuple[DecisionState, ReasonCode, dict]:
        pp = di.platform_policy
        if not pp.platform_id:
            return (
                current.model_copy(deep=True),
                ReasonCode.PLATFORM_NO_POLICY, {},
            )

        if pp.required_sections:
            missing = pp.required_sections - di.present_sections
            if missing:
                return (
                    DecisionState(action=DecisionAction.BLOCK, risk_level=RiskLevel.CRITICAL, requires_human_review=True),
                    ReasonCode.PLATFORM_MISSING_SECTION,
                    {"platform_id": pp.platform_id, "missing": sorted(missing)},
                )

        return (
            current.model_copy(deep=True),
            ReasonCode.PLATFORM_PASSTHROUGH,
            {"platform_id": pp.platform_id},
        )

    def _eval_hard_rule(
        self, di: DecisionInput, current: DecisionState,
    ) -> tuple[DecisionState, ReasonCode, dict]:
        # ── parameter bias findings (HARD_RULE sub-layer, executed first) ──
        bias_result = self._eval_bias(di, current)

        # ── rule violations ──
        rule_result = self._eval_rule_violations(di, current)

        # Merge: bias + rules, escalate to the stricter of the two
        action = _max_action(bias_result[0].action, rule_result[0].action)
        risk = _max_risk(bias_result[0].risk_level, rule_result[0].risk_level)
        hr = bias_result[0].requires_human_review or rule_result[0].requires_human_review

        # Reason code: prefer the more specific one (bias > rules > passthrough)
        if bias_result[1] != ReasonCode.HARD_RULE_PASSTHROUGH:
            code = bias_result[1]
            params = bias_result[2]
        elif rule_result[1] != ReasonCode.HARD_RULE_PASSTHROUGH:
            code = rule_result[1]
            params = rule_result[2]
        else:
            code = ReasonCode.HARD_RULE_NONE
            params = {}

        return (
            DecisionState(action=action, risk_level=risk, requires_human_review=hr),
            code, params,
        )

    def _eval_bias(
        self, di: DecisionInput, _current: DecisionState,
    ) -> tuple[DecisionState, ReasonCode, dict]:
        """参数倾向性发现 → HARD_RULE 层子评估。

        语义：bias 是参数分析工具发现的倾向性证据，不是法律确定违规。
        因此不对单条 bias 自动 BLOCK — 需要 rule_violations 协同才可能 block。
        """
        if not di.bias_findings:
            return (
                _current.model_copy(deep=True),
                ReasonCode.HARD_RULE_PASSTHROUGH, {},
            )

        max_severity = max(di.bias_findings, key=lambda b: _RISK_RANK.get(b.severity, 0))
        sev = max_severity.severity

        if sev == RiskLevel.CRITICAL:
            return (
                DecisionState(action=DecisionAction.REQUIRE_REVIEW, risk_level=RiskLevel.CRITICAL, requires_human_review=True),
                ReasonCode.HARD_RULE_BIAS_CRITICAL,
                {"count": len(di.bias_findings), "max_severity": sev.value,
                 "pattern_ids": [b.pattern_id for b in di.bias_findings]},
            )
        elif sev == RiskLevel.HIGH:
            return (
                DecisionState(action=DecisionAction.REQUIRE_REVIEW, risk_level=RiskLevel.HIGH, requires_human_review=True),
                ReasonCode.HARD_RULE_BIAS_HIGH,
                {"count": len(di.bias_findings), "max_severity": sev.value,
                 "pattern_ids": [b.pattern_id for b in di.bias_findings]},
            )
        elif sev == RiskLevel.MEDIUM:
            return (
                DecisionState(action=DecisionAction.WARN, risk_level=RiskLevel.MEDIUM, requires_human_review=True),
                ReasonCode.HARD_RULE_BIAS_MEDIUM,
                {"count": len(di.bias_findings), "max_severity": sev.value,
                 "pattern_ids": [b.pattern_id for b in di.bias_findings]},
            )
        else:
            # low bias: advisory only, no escalation
            return (
                _current.model_copy(deep=True),
                ReasonCode.HARD_RULE_PASSTHROUGH,
                {"bias_low_count": len(di.bias_findings)},
            )

    def _eval_rule_violations(
        self, di: DecisionInput, current: DecisionState,
    ) -> tuple[DecisionState, ReasonCode, dict]:
        if not di.rule_violations:
            return (
                current.model_copy(deep=True),
                ReasonCode.HARD_RULE_PASSTHROUGH, {},
            )

        forbidden = [rv for rv in di.rule_violations if rv.rule_type == RuleType.FORBIDDEN]
        highs = [rv for rv in di.rule_violations if rv.risk_level == RiskLevel.HIGH]
        chapters = [rv for rv in di.rule_violations if rv.rule_type == RuleType.CHAPTER_REQUIRED]

        if len(forbidden) >= 2:
            return (
                DecisionState(action=DecisionAction.BLOCK, risk_level=RiskLevel.CRITICAL, requires_human_review=True),
                ReasonCode.HARD_RULE_MULTI_FORBIDDEN, {"count": len(forbidden)},
            )
        if forbidden and highs:
            return (
                DecisionState(action=DecisionAction.BLOCK, risk_level=RiskLevel.HIGH, requires_human_review=True),
                ReasonCode.HARD_RULE_FORBIDDEN_HIGH, {"forbidden": len(forbidden), "high": len(highs)},
            )
        if forbidden:
            return (
                DecisionState(action=DecisionAction.REQUIRE_REVIEW, risk_level=RiskLevel.HIGH, requires_human_review=True),
                ReasonCode.HARD_RULE_FORBIDDEN, {"forbidden": len(forbidden)},
            )
        if chapters:
            return (
                DecisionState(action=DecisionAction.REQUIRE_REVIEW, risk_level=RiskLevel.MEDIUM, requires_human_review=True),
                ReasonCode.HARD_RULE_MISSING_CHAPTER, {"count": len(chapters)},
            )
        if highs:
            return (
                DecisionState(action=DecisionAction.WARN, risk_level=RiskLevel.MEDIUM, requires_human_review=True),
                ReasonCode.HARD_RULE_HIGH, {"count": len(highs)},
            )
        return (
            current.model_copy(deep=True),
            ReasonCode.HARD_RULE_PASSTHROUGH, {"count": len(di.rule_violations)},
        )


# ═══════════════════════════════════════════════════════════════
# Trace 验证
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# Version routing — 集中式版本分发
# ═══════════════════════════════════════════════════════════════

_V2_KNOWN = frozenset({PolicySchemaVersion.V2_0_0.value, PolicySchemaVersion.V2_1_0.value})


def parse_decision_input_for_version(raw: dict):
    """根据原始 payload 的 schema_version 选择对应的输入模型。

    - 2.0.0 → DecisionInputV2_0 (extra="forbid")
    - 2.1.0 → DecisionInput
    返回 (DecisionInput | DecisionInputV2_0)。
    未知版本 → ValueError fail-closed。
    """
    sv = raw.get("schema_version", "")
    if sv not in _V2_KNOWN:
        raise ValueError(f"Unsupported policy schema version: {sv!r}")
    if sv == PolicySchemaVersion.V2_0_0.value:
        return DecisionInputV2_0.model_validate(raw)
    return DecisionInput.model_validate(raw)


def verify_trace_for_version(raw_input: dict, raw_decision: dict) -> dict:
    """版本化 trace 验证 — 解析版本化输入后委托统一 verify_trace。

    - 2.0.0 → DecisionInputV2_0 → verify_trace
    - 2.1.0 → DecisionInput → verify_trace
    未知版本 → fail-closed。
    """
    di_sv = raw_input.get("schema_version", "")
    pd_sv = raw_decision.get("schema_version", "")

    if di_sv not in _V2_KNOWN or pd_sv not in _V2_KNOWN:
        return {
            "valid": False,
            "integrity_status": "unsupported_version",
            "errors": [f"Unsupported schema version: input={di_sv!r}, decision={pd_sv!r}"],
            "checks": {},
        }
    if di_sv != pd_sv:
        return {
            "valid": False,
            "integrity_status": "version_mismatch",
            "errors": [f"Schema version mismatch: input={di_sv!r}, decision={pd_sv!r}"],
            "checks": {},
        }

    kernel = PolicyKernel()
    if di_sv == PolicySchemaVersion.V2_0_0.value:
        try:
            di = DecisionInputV2_0.model_validate(raw_input)
        except Exception as e:
            return {"valid": False, "integrity_status": "parse_error",
                    "errors": [f"2.0.0 parse failed: {e}"], "checks": {}}
    else:
        # 2.1.0
        try:
            di = DecisionInput.model_validate(raw_input)
        except Exception as e:
            return {"valid": False, "integrity_status": "parse_error",
                    "errors": [f"2.1.0 parse failed: {e}"], "checks": {}}

    pd = PolicyDecision.model_validate(raw_decision)
    return verify_trace(di, pd)


def verify_trace(decision_input: DecisionInput | DecisionInputV2_0, decision: PolicyDecision) -> dict:
    """验证 PolicyDecision 的完整性 — 语义回放 + SHA-256 链。

    接受 DecisionInputV2_0 或 DecisionInput，统一路由到 kernel.decide()。
    """
    return _verify_trace_core(PolicyKernel(), decision_input, decision, PolicyKernel().decide)


def _verify_trace_core(kernel, decision_input, decision: PolicyDecision, replay_fn) -> dict:
    """验证 PolicyDecision 的完整性 — 语义回放 + SHA-256 链。

    给定 DecisionInput 和当前 policy schema，判断这个 PolicyDecision
    是否正是 PolicyKernel 应产生的唯一结果。

    验证内容：
    - SHA-256 链自洽（input_hash → 各步 output_hash → decision_hash）
    - semantic replay（重新执行 Kernel 并逐字段对比）
    - 五层完整，source 序列精确匹配
    - 每步 state_after >= state_before（无降级）

    返回 {"valid": True/False, "integrity_status": str, "errors": [...], "checks": {...}}

    边界声明：
      SHA-256 链提供可重复审计和一致性校验，不提供数据库攻击者级别的
      真实性证明。如需不可伪造性，请使用 HMAC 或数字签名。
    """
    errors: list[str] = []
    checks: dict[str, bool] = {}

    # ── 0. 基础结构检查 ──
    if not decision.trace_chain:
        errors.append("empty trace_chain")
        checks["trace_count"] = False
    else:
        checks["trace_count"] = len(decision.trace_chain) == 5
        if not checks["trace_count"]:
            errors.append(f"expected 5 trace steps, got {len(decision.trace_chain)}")

    # ── 1. Semantic replay ──
    try:
        expected = replay_fn(decision_input)
    except Exception as e:
        errors.append(f"replay failed: {e}")
        return {"valid": False, "integrity_status": "replay_error", "errors": errors, "checks": checks}

    if expected.decision_hash != decision.decision_hash:
        checks["replay_semantic_match"] = False
        errors.append(f"replay produced different decision_hash: {expected.decision_hash[:16]}... vs {decision.decision_hash[:16]}...")
    else:
        checks["replay_semantic_match"] = True

    # ── 2. Input hash ──
    expected_root = sha256_hex(_canonical_json(decision_input))
    checks["root_hash"] = decision.input_hash == expected_root
    if not checks["root_hash"]:
        errors.append("input_hash mismatch")

    # ── 3. Full structural diff against replay output ──
    for field in ["final_action", "final_risk_level", "requires_human_review", "overrides_applied"]:
        expected_val = getattr(expected, field)
        actual_val = getattr(decision, field)
        if field == "overrides_applied":
            expected_val = sorted(expected_val)
            actual_val = sorted(actual_val)
        checks[f"final_{field}"] = expected_val == actual_val
        if not checks[f"final_{field}"]:
            errors.append(f"final.{field}: expected {expected_val}, got {actual_val}")

    # ── 4. Trace step-by-step comparison ──
    for i, (exp_step, act_step) in enumerate(zip(expected.trace_chain, decision.trace_chain)):
        for attr in ["execution_index", "priority_rank", "source", "reason_code",
                      "reason_params", "state_before", "proposed_transition",
                      "state_after", "input_hash", "output_hash"]:
            exp_val = getattr(exp_step, attr)
            act_val = getattr(act_step, attr)
            match = exp_val == act_val
            checks[f"trace[{i}].{attr}"] = match
            if not match:
                errors.append(f"trace[{i}].{attr}: expected {exp_val}, got {act_val}")

    # ── 5. Canonical source sequence ────────────────
    expected_sources = ["llm", "ux", "tenant", "platform", "hard_rule"]
    actual_sources = [t.source.value for t in decision.trace_chain] if decision.trace_chain else []
    checks["source_sequence"] = actual_sources == expected_sources
    if not checks["source_sequence"]:
        errors.append(f"source sequence mismatch: expected {expected_sources}, got {actual_sources}")

    # ── 6. Chain continuity ──
    trace = decision.trace_chain
    for i, step in enumerate(trace):
        if i == 0:
            if step.input_hash != decision.input_hash:
                errors.append(f"trace[{i}].input_hash != root_hash")
                checks[f"trace[{i}].chain_input"] = False
            else:
                checks[f"trace[{i}].chain_input"] = True
        else:
            expected_in = trace[i - 1].output_hash
            if step.input_hash != expected_in:
                errors.append(f"trace[{i}].input_hash chain broken")
                checks[f"trace[{i}].chain_input"] = False
            else:
                checks[f"trace[{i}].chain_input"] = True

    # ── 7. No downgrade check ──
    for i, step in enumerate(trace):
        sb = step.state_before
        sa = step.state_after
        if _ACTION_RANK.get(sa.action, 0) < _ACTION_RANK.get(sb.action, 0):
            errors.append(f"trace[{i}] action downgraded")
            checks[f"trace[{i}].no_downgrade"] = False
        elif _RISK_RANK.get(sa.risk_level, 0) < _RISK_RANK.get(sb.risk_level, 0):
            errors.append(f"trace[{i}] risk downgraded")
            checks[f"trace[{i}].no_downgrade"] = False
        else:
            checks[f"trace[{i}].no_downgrade"] = True

    valid = len(errors) == 0

    # ── 8. Integrity status ──
    if valid:
        status = "verified"
    else:
        if not checks.get("root_hash", False) and len(errors) == 1:
            status = "input_hash_mismatch"
        elif not checks.get("replay_semantic_match", True):
            status = "replay_mismatch"
        else:
            status = "integrity_failed"

    return {"valid": valid, "integrity_status": status, "errors": errors, "checks": checks}


# ═══════════════════════════════════════════════════════════════
# PolicyDecision → 兼容映射 (merge_*)
# ═══════════════════════════════════════════════════════════════

class ReviewStatus(str, Enum):
    AUTO_PASSED = "auto_passed"
    AUTO_FAILED = "auto_failed"
    NEEDS_REVIEW = "needs_review"
    REVIEWED_PASSED = "reviewed_passed"
    REVIEWED_FAILED = "reviewed_failed"


def derive_merge_fields(decision: PolicyDecision) -> dict[str, Any]:
    """从 PolicyDecision 单向派生 merge_* 兼容字段。"""
    action = decision.final_action
    if action == DecisionAction.PASS:
        review_status = ReviewStatus.AUTO_PASSED
    elif action == DecisionAction.BLOCK:
        review_status = ReviewStatus.AUTO_FAILED
    else:
        review_status = ReviewStatus.NEEDS_REVIEW

    return {
        "final_passed": action == DecisionAction.PASS,
        "risk_level": decision.final_risk_level.value,
        "review_status": review_status.value,
        "requires_human_review": decision.requires_human_review,
    }


# ═══════════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════════

policy_kernel = PolicyKernel()
