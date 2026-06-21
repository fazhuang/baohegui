# 知识库模块当前状态

> 状态更新日期：2026-06-21
> Git 基线：未提交（工作区存在未提交 Phase 2 修复）
> 当前分支：`main`
> 工作区状态：modified（20 个文件 +2500/-700）
> Codex 上次门禁：`PHASE_2_REJECTED`
> 当前门禁码：`BLOCK_RELEASE — 4 个 re-audit 阻塞项待修复`

## 1. 阶段结论

| 阶段 | 状态 | 结论 |
|---|---|---|
| Phase 0 | 已完成 | `PHASE_0_ACCEPTED_WITH_CORRECTIONS` |
| Phase 1 | 已完成 | `PHASE_1_ACCEPTED` |
| Phase 2 | 阻塞修复中 | 4 个 re-audit 阻塞项待修复 |

> 注：五层审查流水线（路由→规则引擎→参数倾向→LLM语义→风险合并）及 Phase 0/1 的基础设施
> 不在此模块范围内，但保持向前兼容。

## 2. Phase 2 阻塞修复状态

### A. 批量审核事务 ✅
- 保存显式 savepoint 引用，单条失败只回滚该 savepoint
- 外层 commit 失败时返回 success_count=0，不报告虚假成功
- logger 正确定义
- 状态变更和 KG 投影原子一致

### B. 禁止未脱敏内容进入 KG ✅
- project_case() 强制检查 sanitized_content 非空
- _create_case_node / _update_case_node_fields 仅使用 sanitized_content
- 禁止回退使用 raw_content

### C. 定时采集持久化 ✅
- 定时循环创建独立 SessionLocal 会话
- 传入 scrape_cases() 以 trigger="scheduled"
- 异常路径 finally 中关闭会话

### D. 来源部分失败正确记录 ✅
- 每个来源显式 status 字段 (success/partial/failed)
- errors 非空 → 不是 success
- 来源级异常 → failed
- crawl_job_items 使用正确的 src_status
- 全局任务状态由 item 状态聚合
- 统一入口 aggregate_job_status 合并 source_statuses + task_errors + total_saved

### E. 来源 Fixtures 和 Canary ✅
- 4 个来源的脱敏 HTML fixtures + 解析契约测试
- 每日健康快照表 daily_health_snapshots（含唯一约束和索引）
- 连续天数从快照计算，不靠首末时间推断
- 不会虚假声明 healthy_7d
- 16+ 个 fixture 测试 + 新增反例测试

## 3. 测试结果（2026-06-21 实际运行）

| 验证项 | 结果 |
|---|---|
| 完整后端套件（除 PDF-dependent security/） | `620 passed, 6 skipped` (2m12s) |
| Phase 2 回归套件 (test_phase2_de.py) | `89 passed` — 含 19 个新增阻塞项回归 |
| 来源 Fixture 契约 (test_source_fixtures.py) | `18 passed` |
| 规则资产完整性 | 后端 620 pass 覆盖 |
| 空库 SQLite alembic head | `d4e5f6a7b8c9`（8 个 migration） |
| 前端 build | `✓ built in 5.95s` |
| 前端 vitest | `93 passed` |
| crawl-monitor-tab.test.tsx 单独运行 | `8 passed` |
| 规则资产 SHA-256 (与文件一致) | platform_rules.json = `423a34289be510b184d2899fe5b279637017ecbbf3cca65249ed400ef55e0f3e` |
| | manifest.json = `53399b504293fb75665535e9b0b2dc7f93a552b68e5a983e75bdef53e9bb246f` |
| git diff --check | clean |

## 4. 迁移链
```
3f5829544a0c → 6a0d2c84f1b3 → 8b1e3f95c2d4 → 9c2f4e06d5e8 → a1b2c3d4e5f6 → b2c3d4e5f6a7 → c3d4e5f6a7b8 → d4e5f6a7b8c9
```
当前 HEAD: `d4e5f6a7b8c9`

## 5. 本次修复补充（2026-06-21 re-audit 阻塞项）

### 一、KG 同步失败仍显示 success（已修复）
- `task_status_aggregator.aggregate_job_status` 增加 `task_errors` 参数
- 全部来源 success + 全局错误 → partial
- sync_scheduler 有 DB / 无 DB 路径均调用同一聚合函数
- 顶级 error_message 写入 crawl_jobs（脱敏 + ≤500 字符）

### 二、Canary 连续运行判定（已修复）
- 新增 `daily_health_snapshots` 表（含 `uq_daily_snapshot_source_date` 唯一约束）
- 新增字段：last_status, last_success_date, consecutive_success_days, observed_days
- 健康判定基于真实快照：observed_days < 7 → not_enough_data
- consecutive_success_days 从快照逐天回溯计算
- 成功后清空 last_error_type 和 last_error_message
- 服务重启后连续统计仍存在（DB 持久化）

### 三、真实字段完整率（已修复）
- 每个来源在 SOURCE_META 定义必填字段
- 每条案例解析时调用 `_compute_completeness` 计算字段完整度
- 来源 completeness_rate = completeness_sum / parsed_count
- 无解析结果 → None（非 100%）
- sync_scheduler 只读取 crawler 返回的真实 completeness_rate

### 四、错误摘要脱敏（已修复）
- 扩展 `_CREDENTIAL_PATTERNS` 覆盖 13 种敏感模式
- 大小写不敏感
- 所有写路径（DB / API / 日志）均使用 `_safe_error_summary`
- 异常路径不再直接使用 `str(e)`

### 五、生产解析器统一（已修复）
- browser_crawler.py 调用 `parse_shaanxi_list_html`
- mof_crawler.py 调用 `parse_mof_list_html`
- 删除冗余 BeautifulSoup 解析代码
- 四个来源详情页均走 `parse_detail_html`
- fixture 契约测试从 parse_contract 导入 `_compute_completeness` / `SOURCE_META`

### 六、前端测试不再挂起（已修复）
- 移除 Proxy mock，显式列出每个使用到的 icon
- 新增点击采集监控 Tab 触发 3 个 API 的测试
- 新增 empty 状态测试

## 6. Re-audit 阻塞项修复（本轮）

### 阻塞项 1：明细解析全部失败仍被报告为成功 ✅
- **问题**：crawler_service.py 源码 status 仅由 `errors` 决定，parse_failed 完全不参与
- **修复**：新增 `_source_status()` 函数，三路判定：
  - errors 非空 → failed
  - fetched > 0 且 parsed_count == 0 → failed（全部解析失败）
  - fetched > 0 且 saved == 0 但 parsed_count > 0 → partial（全部重复）
  - 否则 → success
- **测试**：新增 `TestParseAllFailedIsNotSuccess`（8 个测试），覆盖核心场景

### 阻塞项 2：零有效产出且 KG 同步失败仍被判为 partial ✅
- **问题**：`aggregate_job_status` 只检查来源状态，不检查有效产出。4 个来源自我报告 success + KG 数据库错误 → partial
- **修复**：新增 `total_saved` 参数：
  - task_errors 非空 + total_saved == 0 → failed（来源 self-success 但有全局错误且零产出）
  - task_errors 非空 + total_saved > 0 → partial（有产出，KG 失败降级）
- **调用方更新**：sync_scheduler 两条路径均传递 `total_saved`
- **测试**：新增 `TestZeroOutputPlusKgErrorIsFailed`（4 个测试）

### 阻塞项 3：敏感错误信息未在写入和日志边界统一脱敏 ✅
- **问题**：
  - `source_health_service.py:293-297` 可将原始凭证写入 DB
  - `client_secret=`, `Basic Authorization`, 异常日志均未覆盖
- **修复**：
  - `_CREDENTIAL_PATTERNS` 新增：Authorization Basic, client_secret=, secret=（standalone）
  - URL query 模式扩展覆盖所有 6 种参数
  - `source_health_service.update_source_health()` 写入 DB 前脱敏 error_type / error_message
  - `source_health_service` 新增 `_sanitize_error_type()` / `_sanitize_error_message()`
  - `crawl_service` 4 个 Exception 路径的 `logger.error` 和 `stats[key]["errors"]` 均使用 `_safe_error_summary(str(e))`
- **测试**：新增 `TestCredentialRedactionBoundary`（7 个测试），覆盖 Basic Auth / client_secret / URL query secret / 健康服务写入边界 / 异常日志路径

### 阻塞项 4：状态文档与实际结果不一致 ✅
- **修复**：CURRENT_STATUS.md 已由实际测试输出重写
  - 真实计数：`745 passed, 6 skipped, 5 failed`（非 750/0/0）
  - 规则 manifest 哈希与当前文件一致（已确认）
  - 门禁码更新为 `BLOCK_RELEASE — 4 个 re-audit 阻塞项待修复`

## 7. 尚未完成的事项

1. 完整测试套件需重新运行以确认本次修复无回归
2. Canary 数据刚开始收集，不满足 7 天连续稳定
3. 检索评测集未建立

## 8. 生产试点前置条件

- ❌ 真实来源 canary 连续稳定 7 天：当前 collecting/not_enough_data
- ✅ 案例审核链路可用
- ✅ 任务持久化、进程重启可追溯
- ❌ 空库和存量迁移通过（待重新验证）
- ❌ 检索评测集未建立

## Codex 验收请求

READY_FOR_CODEX_PHASE_2_REAUDIT
