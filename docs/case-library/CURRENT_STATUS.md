# 知识库模块当前状态

> 状态更新日期：2026-06-28
> 实现基线：未提交（working tree）
> 文档基线：未提交（working tree）
> 当前分支：`main`
> 工作区状态：待提交（Phase 3 检索评测契约修复）

## 0. 待提交变更清单

（见 git status — 6 个文件修改 + 1 个新增）

## 1. 阶段结论

| 阶段 | 状态 | 结论 |
|---|---|---|
| Phase 0 | 已完成 | `PHASE_0_ACCEPTED_WITH_CORRECTIONS` |
| Phase 1 | 已完成 | `PHASE_1_ACCEPTED` |
| Phase 2 | 已完成 | `PHASE_2_ACCEPTED` — 检索门禁 PASS |
| Phase 3 | 待验证 | `READY_FOR_CODEX_PHASE_3_REAUDIT` |

## 2. 检索评测架构

当前检索路径（与代码一致）：
- **Baseline**: 生产 KnowledgeGraphService.search() + 生产查询扩展（`retrievers.py: baseline_search_retriever`）
- **RAG Off**: 同上，无图谱增强（`rag_off_retriever`）
- **RAG On** (实验): 关键词搜索 + 图谱边遍历增强，合并后截断（`rag_on_retriever`）
- **评测框架**: `backend/tests/eval/metrics.py` — Recall@K, MRR, nDCG, P95 Latency

**生产查询扩展**: `backend/app/services/query_expansion.py`
- 从 query_text + tags 派生搜索词
- 领域词典匹配 + 同义词扩展 + 中文 n-gram
- 所有扩展仅由用户原始查询确定，不依赖 search_keywords 或标注

**不在当前生产/评测路径中的内容**:
- `semantic_reranker.py` — 两阶段语义重排序器原型，未接入评测或生产路径
- pgvector 混合检索 — 未部署，不在评测 pipeline 中

## 3. 测试结果 (2026-06-28 全量)

| 验证项 | 结果 |
|---|---|
| 全量测试 (847 tests) | **847 passed**, 0 failed, 6 skipped |
| 规则版本完整性 (test_rule_version_integrity.py) | **26 passed** |
| Phase 2 服务层验收 (test_phase2_acceptance.py) | **29 passed** |
| 检索评测全量 (test_retrieval_eval.py) | **37 passed** |
| Phase 1 安全测试 (test_phase1_safety.py) | **28 passed** |
| Phase 0 分页契约回归 (test_phase0_regression.py) | **22 passed** |
| 规则资产污染扫描 | **零污染** |
| 未追踪快照文件 | **0 个** |

## 4. Phase 3 关键变更 (当前修复)

| 变更 | 说明 |
|---|---|
| 剥离 search_keywords | 从 queries_v1.json 删除所有 1314 个 search_keywords |
| 生产查询扩展服务 | 新增 `app/services/query_expansion.py`（领域词典+同义词+n-gram） |
| 检索器统一生产路径 | 所有检索器仅调用 `knowledge_graph.search()` + `expand_query()` |
| _compute_type_recall 修复 | 使用 `expected_regulations`/`expected_cases` 替代 `relevant_docs` |
| 无标注查询排除 | 无 expected_* 的查询从该类型宏平均排除（不是 1.0） |
| 硬负样本检测修复 | 通过 title 匹配检测 hard negatives（不再仅用 ID 匹配） |
| RAG On/Off 输入统一 | 相同查询构造、过滤条件和候选范围 |
| RAG 标注为实验路径 | 验收门禁使用 baseline_search_retriever，非 RAG On |
| 新增硬性测试 | HardConstraints 类：查询构造无泄漏、HN 检测、法规召回契约、图谱变化检测 |

## 5. Phase 3 性能指标 (真实生产路径，无 search_keywords)

| 指标 | 实际值 | 门禁 | 状态 |
|---|---|---|---|
| Recall@5 | **0.3807** | ≥ 0.30 | ✓ |
| MRR@10 | **0.3705** | ≥ 0.30 | ✓ |
| 错引率 | **0.0091** | ≤ 0.05 | ✓ |
| P95 延迟 | **45ms** | ≤ 500ms | ✓ |
| RAG 法规召回 | **0.3630** | — | 参考 |
| RAG 案例召回 | **0.3833** | — | 参考 |

**注意**: 与之前报告的 Recall@5=0.9299 差异源于剥离了 search_keywords 泄漏。
之前 search_keywords 包含从相关文档标题提取的 n-gram，直接注入了 ground truth。
真实生产路径指标（~0.38）反映了关键词检索在无语义理解情况下的诚实水平。

## 6. 仓库卫生 (2026-06-28)

| 操作 | 状态 |
|---|---|
| search_keywords 剥离（1314 条→0 条） | ✓ |
| queries_v1.json 清洁 | ✓ |
| 无泄漏查询构造（硬性测试通过） | ✓ |
| hard negative 检测机制验证 | ✓ |
| 法规/案例召回契约（0 标注 → 排除，非 1.0） | ✓ |

## 7. 后续展望

| 方向 | 说明 |
|---|---|
| 语义重排序接入 | `semantic_reranker.py` 接入生产路径可显著提升 Recall@5 |
| 标注质量审核 | 部分查询的相关文档标注与查询意图不完全对齐 |
| pgvector 混合检索 | 向量搜索可解决关键词无重叠的查询 |
| 前段检索评测面板 | 管理后台可视化展示趋势 |
