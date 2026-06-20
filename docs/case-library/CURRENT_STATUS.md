# 知识库模块当前状态

> 状态更新日期：2026-06-20
> Git 基线：`a7e39f1f`
> 当前分支：`main`
> 工作区状态：Phase 2 修复中
> 当前门禁：等待 Codex 重新审计

## 1. 阶段结论

| 阶段 | 状态 | 结论 |
|---|---|---|
| Phase 0：现状审计与基线冻结 | 已完成 | `PHASE_0_ACCEPTED_WITH_CORRECTIONS` |
| Phase 1：安全、数据隔离与采集可靠性 | 已完成 | `PHASE_1_ACCEPTED` |
| Phase 2：案例运营闭环 | 修复中 | 阻塞项 A-D 已完成，E 部分完成，F 已完成 |
| Phase 3：检索质量工程 | 未开始 | 依赖可运营的数据闭环和评测集 |
| Phase 4：法规、术语和模板产品化 | 未开始 | 不应提前扩张 |

## 2. Phase 2 阻塞修复状态

### ✅ A. 重新发布恢复 RAG 可见性
- `kg_projection.py`: `project_case()` 幂等判断扩展为 4 因素（content_hash + audit_status + unprojected_at + sync_version）
- 新增 `_restore_case_node()`: rejected → verified，清除 unprojected_at
- 新增 `_update_case_node_fields()`: DRY 字段更新
- `unproject_case()`: 设置 unprojected_at + 降低 trust_level
- 测试: `TestPublishUnpublishRepublishCycle` 7 个新增测试 pass

### ✅ B. KG 投影失败事务回滚
- `case_review.py`: per-case savepoint，KG 投影失败时 rollback
- 状态变更与 KG 投影原子操作
- 单条失败不破坏其他成功项
- 已移除 post-commit 分离的 KG 投影

### ✅ C. 规则资产污染清理
- `platform_rules.json` 恢复为基线版本（26 条规则，NATL-001 enabled=true, description=缺少规定章节）
- `manifest.json` 恢复为基线版本
- 所有 tracked 快照恢复为基线版本
- 已删除 untracked 污染快照 `rules_20260620102457.json` / `rules_20260620102509.json`
- `rules_20260615185233.json` 已恢复（之前被标记为 Deleted）
- `rg` 扫描确认：零命中

### ✅ D. 采集任务持久化
- 新增模型: `app/models/crawl_job.py` (CrawlJob + CrawlJobItem)
- 新增服务: `app/services/crawl_job_store.py`
- 新增迁移: `20260620_1200_crawl_jobs.py` (revision: b2c3d4e5f6a7)
- `sync_scheduler.scrape_cases()`: 传入 db_session 时持久化至 crawl_jobs/crawl_job_items
- `crawler.py`: `/api/crawler/status` 从 DB 读取，新增 `/api/crawler/jobs` + `/api/crawler/jobs/{id}` admin 接口
- `crawler_service.crawl_all()`: 返回 per-source fetched/duplicates/error_type
- `database.py` + `env.py`: CrawlJobBase 已注册

### ⚠️ E. 来源 fixtures 和 canary
仅完成数据结构和采集逻辑；解析契约测试和 HTML fixtures 尚未创建。
真实 canary 运行需依赖外网，当前为 "collecting/not_enough_data" 状态。

### ✅ F. 文件纳入版本控制
所有实现依赖已确认存在：
- `case_state_machine.py` ✅
- `candidate_rule.py` ✅
- `candidate_rules.py` ✅
- `case_extraction.py` ✅
- `dedup_service.py` ✅
- `crawl_job.py` ✅
- `crawl_job_store.py` ✅
- `test_phase2_case_ops.py` ✅
- migration `20260620_1200_crawl_jobs.py` ✅

## 3. 测试结果

| 验证项 | 结果 |
|---|---|
| Phase 2 定向门禁（5 测试文件） | `148 passed` |
| 规则资产完整性（2 测试文件） | `32 passed` |
| 完整后端套件 | `662 passed, 6 skipped` |
| 空库 SQLite alembic upgrade head | `b2c3d4e5f6a7`，所有表 + 索引存在 |
| 前端 build | ✅ 通过 |
| 前端 Vitest | `5 files / 85 tests` 通过 |
| 规则污染扫描 | 零命中 |
| git diff --check | 通过 |

## 4. 迁移链

```
3f5829544a0c → 6a0d2c84f1b3 → 8b1e3f95c2d4 → 9c2f4e06d5e8 → a1b2c3d4e5f6 → b2c3d4e5f6a7
```

当前 HEAD: `b2c3d4e5f6a7` (crawl_jobs + crawl_job_items)

## 5. 已知剩余项

1. E 阻塞项：4 个来源的脱敏 HTML fixtures、解析契约测试、canary 7 天运行数据
2. `CandidateRule` 使用独立的 `declarative_base()`（未继承 DocumentBase），表注册通过独立路径
3. 前端 AdminPanel 无 CrawlJob 监控 UI（后端 API 已就绪）
4. canary 数据结构已就绪，但真实运行需外网采集 — 当前状态: `collecting/not_enough_data`
5. `backend/tests/.test_tmp` 是固定共享目录，后端测试必须串行运行

## 6. 生产试点仍需满足

- 至少一个真实来源 canary 连续稳定运行 7 天
- 案例审核、脱敏、发布、下架和审计链路可用
- 任务和重试状态持久化，进程重启后可恢复或追溯
- 空库迁移和已有数据升级迁移均通过
- 建立检索离线评测集并达到既定 Recall、MRR 和错引率门槛
- RAG on/off 对照证明有净收益

## 7. 历史证据

- Phase 0 基线：`docs/case-library/PHASE_0_BASELINE.md`
- Phase 0 Codex 审计：`docs/case-library/PHASE_0_CODEX_AUDIT.md`
- 完整复核审计：`docs/case-library/PHASE_1_AUDIT_REPORT.md`

## Codex 验收请求

READY_FOR_CODEX_PHASE_2_REAUDIT
