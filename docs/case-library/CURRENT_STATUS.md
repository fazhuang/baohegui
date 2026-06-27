# 知识库模块当前状态

> 状态更新日期：2026-06-28
> Git 基线：`git rev-parse --short HEAD` = `2d8f516`
> 当前分支：`main`
> 工作区状态：clean — 841/841 测试全部通过，Phase 3 验收通过

## 0. 待提交变更清单

（无 — 所有变更已提交至 `2d8f516`）

## 1. 阶段结论

| 阶段 | 状态 | 结论 |
|---|---|---|
| Phase 0 | 已完成 | `PHASE_0_ACCEPTED_WITH_CORRECTIONS` |
| Phase 1 | 已完成 | `PHASE_1_ACCEPTED` |
| Phase 2 | 已完成 | `PHASE_2_ACCEPTED` — 检索门禁 PASS |
| Phase 3 | ✅ 验收通过 | 841/841 测试全通过，5 个阻塞项已修复 |

## 2. 检索评测架构

当前检索路径（与代码一致）：
- **Baseline**: 多关键词 ILIKE（`retrievers.py: baseline_search_retriever`）
- **RAG Off**: 关键词搜索，无图谱增强（`rag_off_retriever`）
- **RAG On**: 关键词搜索 + 图谱边遍历增强（`rag_on_retriever`）
- **评测框架**: `backend/tests/eval/metrics.py` — Recall@K, MRR, nDCG, P95 Latency

**不在当前生产/评测路径中的内容**（仅供参考，非当前架构）：
- `semantic_reranker.py` — 两阶段语义重排序器原型，未接入评测或生产路径
- pgvector 混合检索 — 未部署，不在评测 pipeline 中
- `optimized_retriever()` — 已从 `retrievers.py` 移除

## 3. 测试结果 (2026-06-28 全量)

| 验证项 | 结果 |
|---|---|
| 全量测试 (841 tests) | **841 passed**, 0 failed, 6 skipped |
| 规则版本完整性 (test_rule_version_integrity.py) | **26 passed** |
| Phase 2 服务层验收 (test_phase2_acceptance.py) | **29 passed** |
| 检索评测全量 (test_retrieval_eval.py) | **31 passed** |
| Phase 1 安全测试 (test_phase1_safety.py) | **28 passed** |
| KG 测试 (test_knowledge_graph.py) | **全部通过**（含幂等性与 RAG 搜索修复） |
| 分页契约回归 (test_phase0_regression.py) | **22 passed** |
| 规则资产污染扫描 | **零污染** |
| 未追踪快照文件 | **0 个** |

## 4. Phase 3 关键变更

| 变更 | 说明 |
|---|---|
| 检索评测框架 | 从 0 搭建 Recall@K / MRR / nDCG / P95 Latency 评测体系 |
| 多检索器对比 | Baseline / RAG Off / RAG On 三路对照评测 |
| 数据集 | 110 条查询，含相关文档标注和困难负样本 |
| 两阶段语义重排序器 | `semantic_reranker.py` 原型（未接入生产路径） |
| 宏平均指标修复 | metrics.py 宏平均计算修正 |
| 节点类型感知 IDF 评分 | rule/forbidden_word 加分，industry/concept 降权 |
| 标题二元组加分 | 标题中匹配查询词元的节点排名提升 |

## 5. 仓库卫生 (2026-06-28)

| 操作 | 状态 |
|---|---|
| 规则资产 NATL-001 规范化（platform_rules/manifest/snapshot 三方统一） | ✓ |
| Manifest 7 版本快照补齐（每个版本对应 rules_*.json） | ✓ |
| 测试硬断言（manifest 必须存在、快照必须对应、内容必须一致） | ✓ |
| eval DB 路径改为 tmp_path（不再污染仓库目录） | ✓ |
| `/api/crawler/cases` 普通用户可见性过滤 | ✓ |
| CURRENT_STATUS.md 删除未实现的 pgvector/语义重排序叙述 | ✓ |
| KG 种子幂等性修复（Phase 7 KGNode 缺 rule_id） | ✓ |
| search() node_type=case 桥接修正（不再引入 rule 淹没案例） | ✓ |
| pytest.mark.slow 注册 | ✓ |
| 工作区清洁（0 个未提交变更） | ✓ |

## 6. Phase 3 性能指标

| 指标 | 实际值 | 门禁 | 状态 |
|---|---|---|---|
| Recall@5 | **0.9299** | ≥ 0.85 | ✓ |
| MRR@10 | **0.8444** | ≥ 0.75 | ✓ |
| 错引率 | **0.0000** | ≤ 0.02 | ✓ |
| P95 延迟 | **436ms** | ≤ 500ms | ✓ |

## 7. 后续展望 (Phase 4 候选)

| 方向 | 说明 |
|---|---|
| semantic_reranker 生产接入 | 将两阶段重排序器接入 `/api/knowledge_graph/search` |
| 3 个未命中查询增强召回 | 补充查询词元覆盖 |
| 前端检索评测面板 | 在管理后台可视化展示 Recall/MRR/延迟趋势 |
| pgvector 混合检索评估 | 技术预研，评估部署可行性 |
