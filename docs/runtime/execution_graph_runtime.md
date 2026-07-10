# Execution Graph Runtime

## 概述

Execution Graph Runtime 是 AI 合规执行引擎的调度层，将审查流程建模为有向无环图 (DAG)。

## 核心组件

### ExecutionNode

审查 DAG 中的原子工作单元。每个节点包装一个现有引擎函数，声明其输入/输出 schema、依赖关系、超时和重试策略。

### ExecutionGraph

一次完整审查任务的所有节点及其依赖关系的集合。支持：
- 拓扑排序 (Kahn's algorithm)
- 结构校验（重复 ID、缺失依赖、循环检测）

### ExecutionRuntime

按拓扑序执行图中的节点。关键行为：
- 唯一并行点：RULE_CHECK 和 LLM_CHECK 同时执行（asyncio.gather）
- 节点失败 → 下游节点被跳过（标记为 NodeFailure）
- POLICY_KERNEL 失败 → 可选的 fail-fast 模式（raise ValueError）
- 每个节点输出写入动态 AuditTrace（hash 链）

### AuditTrace (升级版)

从硬编码 8 步序列升级为动态步骤列表。每个 TraceStep 记录：
- 节点 ID、类型、输入/输出 hash
- 前一步 hash（链式验证）
- 执行时间、错误信息

## 11 种节点类型

- FILE_PARSE, OCR, TEXT_NORMALIZE, SECTION_SPLIT
- RULE_CHECK, LLM_CHECK
- EVIDENCE_MAPPING
- FUSION, POLICY_KERNEL
- REPORT_BUILD, FEEDBACK_SNAPSHOT

## 重试策略

每个节点可配置 `RetryPolicy(max_retries, backoff_seconds, backoff_multiplier)`。
重试耗尽的节点输出 NodeFailure，不阻塞最佳努力 (best-effort) 节点。
高风险节点 (POLICY_KERNEL) 失败时可通过 `fail_fast_on_high_risk=True` 立即中止。
