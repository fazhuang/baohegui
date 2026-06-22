# 知识库模块当前状态

> 状态更新日期：2026-06-23
> Git 基线：`190c964e`
> 当前分支：`main`
> 工作区状态：dirty（4 个 Phase 2 re-audit 阻塞项修复中）
> Codex 上次门禁：`PHASE_2_REJECTED`
> 当前门禁码：`BLOCKED_RELEASE` — 4 个阻塞项修复中
> Codex 审计简报：`docs/case-library/CODEX_REAUDIT_BRIEF.md`

## 1. 阶段结论

| 阶段 | 状态 | 结论 |
|---|---|---|
| Phase 0 | 已完成 | `PHASE_0_ACCEPTED_WITH_CORRECTIONS` |
| Phase 1 | 已完成 | `PHASE_1_ACCEPTED` |
| Phase 2 | 修复中 | `PHASE_2_REJECTED` — 4 个 re-audit 阻塞项修复中 |

## 2. 测试结果（2026-06-22）

| 验证项 | 结果 |
|---|---|
| **GitHub Actions CI** | `success` — 0 failed |
| Phase 2 回归套件 (test_phase2_de.py) | `99 passed` — 含 29 个新增阻塞项回归 |
| 规则版本完整性 (test_rule_version_integrity.py) | `24 passed` |
| 来源 Fixture 契约 (test_source_fixtures.py) | `18 passed` |
| Security 全部测试 | 通过 — 含 flaky 修复 |
| 规则资产 SHA-256 | platform_rules.json = `4898677a5637ef900f48dac59af21106168504885ebe1bc1b90fa4af6157af58` |
| | manifest.json = `1627d35ece46b26fc655dacbf05d93099d9744b167248dbd62dc314e70c1bf47` |
| 规则资产污染扫描 | 零污染 — NATL-001 可信基线已恢复 |
| 原始异常日志扫描 | `grep logger.*e)` 空 |
| git status | dirty — 4 个阻塞项修复中 |

## 3. 前一阶段修复汇总（9 个阻塞项，已提交）

| # | 阻塞项 | 提交 |
|---|---|---|
| 1 | 明细解析全部失败仍报告为 success | `8d39f3e5` |
| 2 | 零有效产出 + KG 同步失败判为 partial | `8d39f3e5` |
| 3 | 敏感错误信息未统一脱敏 | `8d39f3e5` |
| 4 | 陕西全部解析失败仍报告 success（fetched=parsed_count）| `9e03e1a8` |
| 5 | 单条明细失败导致整个来源 failed | `7312b20d` |
| 6 | 原始敏感异常可进入 logger | `5dff5565` |
| 7 | sync_scheduler NameError 风险 | `591de418` |
| 8 | NATL-001 无依据文案 + 测试白名单放宽 | `8498217f` + `375648c9` |
| 9 | 状态文档与实际结果不一致 | `375648c9` |

### 额外修复
- CI flaky：uv path / UV_CACHE_DIR / stderr PIPE 诊断 (5 个提交)
- 规则资产清理：61 条测试污染移除、manifest 去重、monkeypatch 加固 (4 个提交)
- Conftest 迁移警告抑制 (`b80b2cbb`)

## 4. 当前在修阻塞项（4 个）

| # | 阻塞项 | 状态 |
|---|---|---|
| 1 | sync_scheduler._safe_error_log 正则不完整 + sync() 方法 raw errors 未脱敏 | 修复中 |
| 2 | SafeFetchError.message 嵌入原始异常，绕过 stats["errors"] 脱敏（safe_fetcher.py 4 处 raw `{e}`） | 修复中 |
| 3 | 陕西部分解析失败仍显示 success：_source_status 未考虑 parse_failed_count（listed=10, parsed=9, parse_failed=1 → success） | 修复中 |
| 4 | CURRENT_STATUS.md 基线 HEAD 不符 + "全部修复" 声明不实 | 修复中 |

## 5. 尚未完成的事项

1. Canary 数据不足 7 天连续稳定
2. 检索评测集未建立
3. 空库和存量迁移待重新验证

## 6. 生产试点前置条件

- ❌ 真实来源 canary 连续稳定 7 天
- ✅ 案例审核链路可用
- ✅ 任务持久化、进程重启可追溯
- ✅ CI 全绿
- ❌ 检索评测集未建立

## Codex 验收请求

**复核审计简报**：`docs/case-library/CODEX_REAUDIT_BRIEF.md`  
**基线提交**：`190c964e`（修复后 HEAD）  
**请求结论**：`READY_FOR_CODEX_PHASE_2_REAUDIT` — 待 4 个阻塞项提交后请求 re-audit
