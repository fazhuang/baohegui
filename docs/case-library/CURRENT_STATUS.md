# 知识库模块当前状态

> 状态更新日期：2026-06-27
> Git 基线：`git rev-parse --short HEAD` = `91dd7d8f`
> 当前分支：`main`
> 工作区状态：dirty — Phase 3 阻塞项修复中

## 0. 待提交变更清单

| 文件 | 变更 | 说明 |
|---|---|---|
| `docs/case-library/CURRENT_STATUS.md` | M | 状态文档更新至真实状态 |
| `backend/tests/eval/retrievers.py` | M | 移除 optimized_retriever() 及 run_full_eval() 中 optimized 分支 |
| `backend/tests/eval/test_retrieval_eval.py` | M | eval DB 路径改为 tmp_path；移除 optimized 分支 |
| `backend/app/services/crawler_service.py` | M | published_only 过滤 + visibility 修复 |
| `backend/app/api/crawler.py` | M | 普通用户案例列表/详情发布状态过滤 |
| `rules/platform_rules.json` | M | 移除 NATL-NATL-001 重复条目，保留 canonical NATL-001 |
| `rules/versions/manifest.json` | M | NATL-NATL-001 → NATL-001；7 版本快照一致性 |
| `rules/versions/rules_20260621102535.json` | M | NATL-NATL-001 移除；rule_count 修正为 25 |
| `rules/versions/rules_20260622102549.json` | A | 新建缺失快照 (manifest 版本) |
| `rules/versions/rules_20260622102601.json` | A | 新建缺失快照 |
| `rules/versions/rules_20260623102615.json` | A | 新建缺失快照 |
| `rules/versions/rules_20260623102627.json` | A | 新建缺失快照 |
| `rules/versions/rules_20260624102641.json` | A | 新建缺失快照 |
| `rules/versions/rules_20260624102653.json` | A | 新建缺失快照 |
| `rules/versions/rules_20260621102523.json` | D | 旧版本快照清理 |
| `backend/tests/test_rule_version_integrity.py` | M | 硬断言：manifest 不可为空、快照必须存在、内容一致 |

## 1. 阶段结论

| 阶段 | 状态 | 结论 |
|---|---|---|
| Phase 0 | 已完成 | `PHASE_0_ACCEPTED_WITH_CORRECTIONS` |
| Phase 1 | 已完成 | `PHASE_1_ACCEPTED` |
| Phase 2 | 已完成 | `PHASE_2_ACCEPTED` — 检索门禁 PASS |
| Phase 3 | 待验收 | Blocker 修复中 |

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

## 3. 测试结果 (2026-06-27 阻断项修复后运行)

| 验证项 | 结果 |
|---|---|
| 规则版本完整性 (test_rule_version_integrity.py) | **26 passed** |
| Phase 2 服务层验收 (test_phase2_acceptance.py) | **29 passed** |
| 检索评测全量 (test_retrieval_eval.py) | **31 passed** |
| 规则资产污染扫描 | **零污染** |
| 未追踪快照文件 | **0 个** |

## 4. Phase 3 关键变更

| 变更 | 说明 |
|---|---|
| 检索评测框架 | 从 0 搭建 Recall@K / MRR / nDCG / P95 Latency 评测体系 |
| 多检索器对比 | Baseline / RAG Off / RAG On 三路对照评测 |
| 数据集 | 110 条查询，含相关文档标注和困难负样本 |

## 5. 仓库卫生 (2026-06-27 阻断项修复)

| 操作 | 状态 |
|---|---|
| 规则资产 NATL-001 规范化（platform_rules/manifest/snapshot 三方统一） | ✓ |
| Manifest 7 版本快照补齐（每个版本对应 rules_*.json） | ✓ |
| 测试硬断言（manifest 必须存在、快照必须对应、内容必须一致） | ✓ |
| eval DB 路径改为 tmp_path（不再污染仓库目录） | ✓ |
| `/api/crawler/cases` 普通用户可见性过滤 | ✓ |
| CURRENT_STATUS.md 删除未实现的 pgvector/语义重排序叙述 | ✓ |
