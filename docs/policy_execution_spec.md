# Policy Execution Kernel — 规范文档

## 背景

当前 `check.py` 中四路结果（routing / rule / parameter_bias / llm）由
`FourWayRiskMerger` 合并，但合并逻辑与审核决策（通过/阻止/人工复核）
耦合在同一个方法里。不同租户、平台没有差异化决策权——所有部署实例
用同一套硬编码的通过条件。

`PolicyKernel` 将"合并"和"决策"拆分为两个阶段：

1. **合并阶段**（现有 `FourWayRiskMerger`）：四路 → 统一风险项
2. **决策阶段**（新增 `PolicyKernel`）：统一风险项 + 策略 → 最终决策

## 强制执行优先级

```
HARD_RULE (L1) > PLATFORM (L2) > TENANT (L3) > UX (L4) > LLM (L5)
```

每层只能向更严格的方向**升级**（escalate），禁止降级（de-escalate）。

| 优先级 | 层级 | 决策能力 | 示例 |
|--------|------|---------|------|
| 最高 | HARD_RULE | 规则引擎发现的确定违规 → block/review | forbidden 规则命中 → block |
| ↓ | PLATFORM | 平台特定规则（章节要求、禁止模式） | 广东平台要求《招标公告》必须存在 |
| ↓ | TENANT | 租户自定义风险偏好 | auto_fail 规则类型、抑制规则列表 |
| ↓ | UX | 展示/交互策略 | 折叠阈值、隐藏低风险项 |
| 最低 | LLM | 大模型语义发现 → 基线决策 | LLM 发现仅 warn，需人工复核 |

## 结构化策略类型

所有策略使用 Pydantic `BaseModel` + `Enum`，禁止裸字符串枚举。

```python
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
    tenant_id: str = "default"
    risk_threshold: RiskLevel = RiskLevel.MEDIUM
    suppressed_rule_ids: set[str] = set()  # 不触发 block 的规则
    auto_fail_rule_types: set[str] = set()  # 直接 block 的规则类型
    requires_human_review_if_llm_only: bool = True
    industries: list[str] = []

class PlatformPolicy(BaseModel):
    platform_id: str = ""
    threshold_overrides: dict[str, float] = {}
    required_sections: set[str] = set()
    additional_forbidden_patterns: list[str] = []
    platform_law_refs: list[str] = []
```

## Hash Trace

每一步生成确定性的 SHA-256 hash（截取前 16 位 hex），链式传递：

```
input_hash = SHA256(rule_violations || llm_violations || tenant || platform)
  → L5 LLM:  input_hash + "LLM" + action + risk → output_hash
  → L4 UX:   output_hash + "UX" + action + risk → output_hash
  → L3 TENANT: ...
  → L2 PLATFORM: ...
  → L1 HARD_RULE: → final output_hash
```

相同输入总是产生相同的 hash trace，支持审计回放验证。

每个 `TraceStep` 记录：
```python
class TraceStep(BaseModel):
    step: int           # 1-5，对应优先级层
    source: PolicySource
    action: DecisionAction
    reason: str         # 决策原因（人类可读）
    input_hash: str
    output_hash: str
```

## 主入口

```python
from app.core.policy_kernel import policy_kernel

decision: PolicyDecision = policy_kernel.decide(
    rule_result=rule_result,
    llm_result=llm_result,
    tenant_policy=tenant_policy,
    platform_policy=platform_policy,
    ux_policy=ux_policy,
)

print(decision.final_action)       # block / require_review / warn / pass
print(decision.final_risk_level)   # critical / high / medium / low
print(decision.requires_human_review)  # bool
print(decision.trace_chain)        # list[TraceStep] — 完整审计链
print(decision.overrides_applied)  # list[str] — 每层升级原因
```

## 与现有代码的集成点

当前 `check.py:298` 调用 `four_way_merger.merge()`。PolicyKernel 在该行**之后**作为独立决策阶段插入：

```python
# 现有：合并
merge_result = four_way_merger.merge(...)

# 新增：策略决策
decision = policy_kernel.decide(
    rule_result=rule_result,
    llm_result=llm_result,
    tenant_policy=tenant_policy,
    platform_policy=platform_policy,
)
```

`MergeResult` 和 `PolicyDecision` 是两个独立的输出，merge_result 提供合并后的风险项列表，PolicyDecision 提供最终行为决策和审计链。

## 测试

20 个测试覆盖：

- 优先级链验证（空输入、单 forbidden、双 forbidden、章节缺失）
- 平台策略（章节缺失阻止、章节满足不升级）
- 租户策略（auto_fail 阻止、抑制规则豁免）
- 降级防护（各层不能降级）
- UX 层透明性（不改变风险判定）
- Hash trace 确定性（相同输入 = 相同 hash，不同输入 = 不同 hash）
- 全层 trace 完整性
- 策略类型结构化校验

运行：`uv run pytest tests/test_policy_kernel.py -v`
