# 知识库模块当前状态

> 状态更新日期：2026-06-21
> Git 基线：`20c0e296`
> 当前分支：`main`
> 工作区状态：clean
> Codex 上次门禁：`BLOCK_RELEASE`
> 当前门禁码：`BLOCK_RELEASE` — 等待 Codex 重新验收

## 1. 阶段结论

| 阶段 | 状态 | 结论 |
|---|---|---|
| Phase 0 | 已完成 | `PHASE_0_ACCEPTED_WITH_CORRECTIONS` |
| Phase 1 | 已完成 | `PHASE_1_ACCEPTED` |
| Phase 2 | 等待重新审计 | 阻塞项 A-E 已修复 |
| Phase 3 | 未开始 | 依赖数据闭环评测集 |
| Phase 4 | 未开始 | 不应提前扩张 |

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

### E. 来源 Fixtures 和 Canary ✅
- 4 个来源的脱敏 HTML fixtures + 解析契约测试
- canary_config.json（status: collecting）
- 不会虚假声明 healthy_7d
- 16 个 source fixture 测试全部通过

## 3. 测试结果

| 验证项 | 结果 |
|---|---|
| 完整后端套件 | `678 passed, 6 skipped` (2m35s) |
| 规则资产完整性 (2 文件) | `32 passed` |
| 空库 SQLite alembic head | `b2c3d4e5f6a7`，9 张表 |
| 前端 build + vitest | build 通过, `85 tests` 通过 |
| 规则资产 SHA-256 | platform_rules.json=b9ec94bf |
| | manifest.json=c5be6c03 |
| git status --short | clean |

## 4. 迁移链
```
3f5829544a0c → 6a0d2c84f1b3 → 8b1e3f95c2d4 → 9c2f4e06d5e8 → a1b2c3d4e5f6 → b2c3d4e5f6a7
```
当前 HEAD: `b2c3d4e5f6a7`

## 5. 尚未完成的事项

1. 来源解析契约未直接调用生产解析器（测试中有独立实现副本）
2. 管理后台 CrawlJob 监控 UI 未实现
3. Canary 数据刚开始收集，不满足 7 天连续稳定
4. 前端 AdminPanel CrawlJob Tab 组件未实现

## 6. 生产试点前置条件

- ❌ 真实来源 canary 连续稳定 7 天：当前 collecting/not_enough_data
- ✅ 案例审核链路可用
- ✅ 任务持久化、进程重启可追溯
- ✅ 空库和存量迁移通过
- ❌ 检索评测集未建立

## Codex 验收请求

READY_FOR_CODEX_PHASE_2_REAUDIT
