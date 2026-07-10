# Policy-as-Code Layer

## 概述

Policy-as-Code 是 PolicyKernel 的上游输入源。PolicyDefinition 通过 PolicyEvaluator 评估后产生 PolicyAction 列表，注入 PolicyKernel 的 UX/TENANT/PLATFORM 层决策输入。PolicyKernel 本身不动。

```
PolicyDefinition[] → PolicyEvaluator.evaluate()
    → PolicyAction[]
    → PolicyKernel.decide() 的 UX/TENANT/PLATFORM 层输入
```

## PolicyAction 枚举

| Action | 说明 |
|--------|------|
| ESCALATE_TO_YELLOW | 风险升级为黄色 |
| ESCALATE_TO_RED | 风险升级为红色 |
| REQUIRE_HUMAN_REVIEW | 强制人工复核 |
| SKIP_LLM_FOR_INDUSTRY | 特定行业跳过 LLM 审查 |
| ADD_EXTRA_RULES | 追加额外规则 |
| WEAKEN_RULE_THRESHOLD | 放宽规则阈值 |
| SUPPRESS_FINDING_IN_REPORT | 报告中隐藏发现 |
| ADD_TENANT_DISCLAIMER | 追加租户免责声明 |

**禁止事项**：无 DISABLE_HARD_RULE — policy 不可关闭硬规则。

## PolicyDefinition

每条 policy 包含：

- `policy_type` — UX | TENANT | PLATFORM
- `scope` — global | tenant:{id} | industry:{code}
- `priority` — 数值越小优先级越高
- `condition` — 复用 ConditionalExpressionEngine 语法（field/op/value）
- `action` — PolicyAction 枚举值
- `effective_from` / `expires_at` — 生效/过期时间窗口
- `approved_by` / `version` — 审批追溯

## PolicyEvaluator

评估逻辑（~60 行）：
1. 按 priority 排序所有 policies
2. 过滤失效/过期/scope 不匹配的 policy
3. 对每个匹配的 policy 评估 condition
4. 输出 PolicyAction 列表

冲突裁决：RED 和 YELLOW 共存 → RED 胜出（只升级不降级）。

条件运算符支持：gte, gt, lte, lt, eq, neq, in。

## DB Schema

```sql
CREATE TABLE policy_definitions (
    policy_id       TEXT PRIMARY KEY,
    policy_type     TEXT NOT NULL,
    scope           TEXT NOT NULL,
    priority        INT NOT NULL,
    condition       JSONB NOT NULL,
    action          TEXT NOT NULL,
    effective_from  TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    approved_by     TEXT,
    version         INT NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

## 禁止事项

1. 在业务代码中散落 if tenant_policy → 统一入口 PolicyEvaluator.evaluate()
2. 在 LLM prompt 中隐式塞策略 → PolicyAction 在 PolicyKernel 层参与裁决，不进 prompt
3. 让 policy 直接关闭 hard rule → 无 DISABLE_HARD_RULE 枚举值
