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
from typing import Any, Optional

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
    # HARD_RULE
    HARD_RULE_NONE = "hard_rule_none"
    HARD_RULE_MULTI_FORBIDDEN = "hard_rule_multi_forbidden"
    HARD_RULE_FORBIDDEN_HIGH = "hard_rule_forbidden_high"
    HARD_RULE_FORBIDDEN = "hard_rule_forbidden"
    HARD_RULE_MISSING_CHAPTER = "hard_rule_missing_chapter"
    HARD_RULE_HIGH = "hard_rule_high"
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
# 策略模型 — 所有字段结构化
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
# DecisionInput — 完整决策输入
# ═══════════════════════════════════════════════════════════════

POLICY_SCHEMA_VERSION = "2.0.0"


class RuleViolationInput(BaseModel):
    """单条规则引擎违规"""
    rule_id: str = ""
    rule_type: RuleType = RuleType.FORBIDDEN
    risk_level: RiskLevel = RiskLevel.MEDIUM
    description: str = ""
    location: str = ""


class LLMViolationInput(BaseModel):
    """单条 LLM 违规"""
    type: str = ""
    risk_level: RiskLevel = RiskLevel.MEDIUM
    reason: str = ""
    validation_error: Optional[str] = None


class BiasFindingInput(BaseModel):
    """单条参数倾向性发现"""
    pattern_id: str = ""
    severity: RiskLevel = RiskLevel.MEDIUM
    description: str = ""
    matched_text: str = ""
    matched_field: str = ""


class RoutingInput(BaseModel):
    """路由审查结果"""
    traffic_light: str = "green"  # green / yellow / red
    skip_llm: bool = False


class ParseQuality(str, Enum):
    OK = "ok"
    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    PARTIAL = "partial"
    FAILED = "failed"


class DecisionInput(BaseModel):
    """系统唯一决策输入 — 所有影响决策的字段必须在此"""
    schema_version: str = POLICY_SCHEMA_VERSION

    # 证据
    routing: RoutingInput = Field(default_factory=RoutingInput)
    rule_violations: list[RuleViolationInput] = Field(default_factory=list)
    bias_findings: list[BiasFindingInput] = Field(default_factory=list)
    llm_violations: list[LLMViolationInput] = Field(default_factory=list)
    parse_quality: ParseQuality = ParseQuality.OK

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
                   "industries", "required_sections"}

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

    输入 DecisionInput，输出 PolicyDecision。
    强制执行优先级 HARD_RULE > PLATFORM > TENANT > UX > LLM。
    每层只能升级，不能降级。

    trace_chain[-1].state_after == PolicyDecision final state（刚性不变量）
    """

    def decide(self, decision_input: DecisionInput) -> PolicyDecision:
        """唯一决策入口"""
        di = decision_input
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

            proposed, code, params = self._evaluate_layer(source, di, state)

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
        self, source: PolicySource, di: DecisionInput, current: DecisionState,
    ) -> tuple[DecisionState, ReasonCode, dict[str, Any]]:
        """评估单层策略，返回 (提案, 原因码, 原因参数)"""
        handlers = {
            PolicySource.LLM: self._eval_llm,
            PolicySource.UX: self._eval_ux,
            PolicySource.TENANT: self._eval_tenant,
            PolicySource.PLATFORM: self._eval_platform,
            PolicySource.HARD_RULE: self._eval_hard_rule,
        }
        return handlers[source](di, current)

    def _eval_llm(
        self, di: DecisionInput, _current: DecisionState,
    ) -> tuple[DecisionState, ReasonCode, dict]:
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
            chapter_violations = [rv for rv in di.rule_violations if rv.rule_type == RuleType.CHAPTER_REQUIRED]
            if chapter_violations:
                present = {rv.location for rv in chapter_violations if rv.location}
                missing = pp.required_sections - present
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
        if not di.rule_violations:
            return (
                current.model_copy(deep=True),
                ReasonCode.HARD_RULE_NONE, {},
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

def verify_trace(decision_input: DecisionInput, decision: PolicyDecision) -> dict:
    """验证 PolicyDecision 的完整性。

    返回 {"valid": True/False, "errors": [...], "checks": {...}}
    任一字段被篡改必须失败。
    """
    errors: list[str] = []
    checks: dict[str, bool] = {}

    # 1. 重算 root hash
    expected_root = sha256_hex(_canonical_json(decision_input))
    checks["root_hash"] = decision.input_hash == expected_root
    if not checks["root_hash"]:
        errors.append(f"input_hash mismatch: got {decision.input_hash}, expected {expected_root}")

    # 2. 链连续性
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
                errors.append(f"trace[{i}].input_hash chain broken: expected {expected_in}, got {step.input_hash}")
                checks[f"trace[{i}].chain_input"] = False
            else:
                checks[f"trace[{i}].chain_input"] = True

    # 3. 重算每一步 hash
    current_hash = decision.input_hash
    recomputed = "<unset>"  # for error messages
    for i, step in enumerate(trace):
        event = {
            "schema_version": decision_input.schema_version,
            "execution_index": step.execution_index,
            "priority_rank": step.priority_rank,
            "source": step.source.value,
            "state_before": step.state_before.model_dump(mode="json"),
            "proposed_transition": step.proposed_transition.model_dump(mode="json"),
            "state_after": step.state_after.model_dump(mode="json"),
            "reason_code": step.reason_code.value,
            "reason_params": step.reason_params,
        }
        event_bytes = _canonical_json(event)
        recomputed = sha256_hex(current_hash.encode() + event_bytes)
        if step.output_hash != recomputed:
            errors.append(f"trace[{i}].output_hash mismatch: expected {recomputed}, got {step.output_hash}")
            checks[f"trace[{i}].hash"] = False
        else:
            checks[f"trace[{i}].hash"] = True
        # Always advance from the stored output_hash (to verify chain continuity)
        current_hash = step.output_hash

    # 4. 检查优先级顺序（strictly descending: 5 > 4 > 3 > 2 > 1）
    for i in range(1, len(trace)):
        if trace[i].priority_rank >= trace[i - 1].priority_rank:
            errors.append(f"trace[{i}] priority_rank {trace[i].priority_rank} not < trace[{i-1}] {trace[i-1].priority_rank}")
            checks["priority_order"] = False
            break
    else:
        checks["priority_order"] = True

    # 5. 检查执行序号
    for i, step in enumerate(trace):
        if step.execution_index != i:
            errors.append(f"trace[{i}] execution_index {step.execution_index} != {i}")
            checks["execution_order"] = False
    checks.setdefault("execution_order", True)

    # 6. terminal 一致性
    last = trace[-1] if trace else None
    if last:
        final_state = DecisionState(
            action=decision.final_action,
            risk_level=decision.final_risk_level,
            requires_human_review=decision.requires_human_review,
        )
        if last.state_after != final_state:
            errors.append(f"terminal mismatch: trace[-1].state_after != final")
            checks["terminal_consistency"] = False
        else:
            checks["terminal_consistency"] = True
    else:
        errors.append("empty trace")
        checks["terminal_consistency"] = False

    # 7. decision_hash
    final_data = _canonical_json({
        "final_action": decision.final_action.value,
        "final_risk_level": decision.final_risk_level.value,
        "requires_human_review": decision.requires_human_review,
        "schema_version": decision.schema_version,
        "input_hash": decision.input_hash,
    })
    expected_dh = sha256_hex(current_hash.encode() + final_data)
    if decision.decision_hash != expected_dh:
        errors.append(f"decision_hash mismatch: expected {expected_dh}, got {decision.decision_hash}")
        checks["decision_hash"] = False
    else:
        checks["decision_hash"] = True

    # 8. 每层只能升级（state_after 不能低于 state_before），且 state_after 必须等于 max(state_before, proposed_transition)
    for i, step in enumerate(trace):
        sb = step.state_before
        sa = step.state_after
        prop = step.proposed_transition

        # 正确升级结果 = max(sb, prop)
        expected_sa = DecisionState(
            action=_max_action(sb.action, prop.action),
            risk_level=_max_risk(sb.risk_level, prop.risk_level),
            requires_human_review=sb.requires_human_review or prop.requires_human_review,
        )

        if sa != expected_sa:
            errors.append(f"trace[{i}] state_after {sa} != expected {expected_sa} (upgrade rule)")
            checks[f"trace[{i}].upgrade_rule"] = False
        else:
            checks[f"trace[{i}].upgrade_rule"] = True

        # 额外降级检查
        if _ACTION_RANK[sa.action] < _ACTION_RANK[sb.action]:
            errors.append(f"trace[{i}] action downgraded")
            checks[f"trace[{i}].no_downgrade"] = False
        elif _RISK_RANK[sa.risk_level] < _RISK_RANK[sb.risk_level]:
            errors.append(f"trace[{i}] risk downgraded")
            checks[f"trace[{i}].no_downgrade"] = False
        else:
            checks[f"trace[{i}].no_downgrade"] = True

    return {"valid": len(errors) == 0, "errors": errors, "checks": checks}


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
