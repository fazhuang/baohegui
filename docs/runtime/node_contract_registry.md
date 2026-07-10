# Node Contract Registry

## 概述

Node Contract Registry 是 Runtime 的防御层。每个 NodeType 必须在启动前注册其契约，未注册节点不可进入执行图。

## SecurityLevel

| Level | 含义 | 示例 |
|-------|------|------|
| STANDARD | 常规节点，失败可降级 | FILE_PARSE, OCR |
| HIGH | 核心审查节点，需审计 | RULE_CHECK, LLM_CHECK, FUSION |
| CRITICAL | 最终裁决节点，不可降级、不可跳过 | POLICY_KERNEL |

## 禁止事项

- RULE_CHECK 不允许被跳过 (degradable=false)
- POLICY_KERNEL 必须最后参与最终结论 (degradable=false, CRITICAL)
- LLM_CHECK 输出不得直接成为最终结论 (中间节点，必须经 FUSION → POLICY_KERNEL)
- OCR 低置信度必须传递风险标记 (output 含 confidence 字段)

## 防御层次

1. 启动时 — `ContractRegistry.validate_all()` —— 失败 → RuntimeError，服务起不来
2. 构建图时 — `ContractRegistry.validate_graph()` —— 未注册 node_type 或字段冲突 → ContractViolationError
3. 执行时 — 输入/输出 schema 校验 —— 不匹配 → ContractViolationError

## 新增节点类型

必须先在 `REGISTRY` dict 中注册 NodeContract，否则 Runtime 拒绝执行。不得绕过。
