# 知识库模块当前状态

> 状态更新日期：2026-06-21
> Git 基线：`9f544c3a`
> 当前分支：`main`
> 工作区状态：clean
> Codex 上次门禁：`PHASE_2_REJECTED`
> 当前门禁码：`READY_FOR_CODEX_PHASE_2_REAUDIT` — 所有阻塞项已修复，CI 全绿

## 1. 阶段结论

| 阶段 | 状态 | 结论 |
|---|---|---|
| Phase 0 | 已完成 | `PHASE_0_ACCEPTED_WITH_CORRECTIONS` |
| Phase 1 | 已完成 | `PHASE_1_ACCEPTED` |
| Phase 2 | 修复完成 | 4 个 re-audit 阻塞项 + CI flaky + 规则污染已全部修复 |

> 注：五层审查流水线（路由→规则引擎→参数倾向→LLM语义→风险合并）及 Phase 0/1 的基础设施
> 不在此模块范围内，但保持向前兼容。

## 2. Phase 2 阻塞修复状态

### A. 批量审核事务 ✅
### B. 禁止未脱敏内容进入 KG ✅
### C. 定时采集持久化 ✅
### D. 来源部分失败正确记录 ✅
### E. 来源 Fixtures 和 Canary ✅

## 3. 测试结果（2026-06-21 CI 实际运行）

| 验证项 | 结果 |
|---|---|
| **完整后端套件 (GitHub Actions)** | **`768 passed, 7 skipped, 0 failed`** ✅ |
| Phase 2 回归套件 (test_phase2_de.py) | `89 passed` — 含 19 个新增阻塞项回归 |
| 规则版本完整性 (test_rule_version_integrity.py) | `24 passed` |
| 来源 Fixture 契约 (test_source_fixtures.py) | `18 passed` |
| Security 子进程测试 (test_production_docs_disabled) | `PASSED` — 不再 flaky |
| 规则资产污染扫描 | 零污染 — platform_rules.json / manifest.json / 所有 28 个快照 |
| 前端 build | `✓ built in 39s` |
| Docker compose 验证 | `3/3 passed` |
| git diff --check | clean |
| git status | clean |

## 4. 迁移链
```
3f5829544a0c → … → b2c3d4e5f6a7 → c3d4e5f6a7b8 → d4e5f6a7b8c9
```
当前 HEAD: `9f544c3a`

## 5. 本轮修复完整清单（2026-06-21）

### 阻塞项 1-4（核心运行时修复）
1. **明细解析全部失败仍被报告为 success** — `_source_status()` 三路判定
2. **零有效产出 + KG 同步失败判为 partial** — `total_saved` 参数 → failed
3. **敏感错误信息未统一脱敏** — `_CREDENTIAL_PATTERNS` 13 种模式 + 写入边界
4. **状态文档不一致** — CURRENT_STATUS.md 重写

### CI 修复（5-stack flaky test chain）
5. `_UV_BIN`: `shutil.which("uv")` 替代硬编码路径
6. `_wait_for_server`: process liveness check + stderr 诊断
7. `UV_CACHE_DIR`: 回退到 `XDG_CACHE_HOME` / `~/.cache/uv`
8. 同样修复应用于 `test_production_config.py`

### 规则资产修复（预存污染清理）
9. `platform_rules.json`: 移除 61 个 TEST-AUDIT/UUID 规则 (87→26)
10. `manifest.json`: 移除测试规则 + 去重重复版本条目 (10→7)
11. 所有 28 个快照文件: 移除 TEST-AUDIT/FILE-T1/UFB/V-TEST 规则
12. `NATL-001.description`: `E2E测试更新` → 规范描述
13. monkeypatch 加固: `RuleSyncService._save` 类级补丁

### 新增测试
- `TestParseAllFailedIsNotSuccess` (8 tests)
- `TestZeroOutputPlusKgErrorIsFailed` (4 tests)
- `TestCredentialRedactionBoundary` (7 tests)

## 6. 尚未完成的事项

1. Canary 数据刚开始收集，不满足 7 天连续稳定
2. 检索评测集未建立
3. 空库和存量迁移待重新验证

## 7. 生产试点前置条件

- ❌ 真实来源 canary 连续稳定 7 天：当前 collecting/not_enough_data
- ✅ 案例审核链路可用
- ✅ 任务持久化、进程重启可追溯
- ✅ CI 全绿 (768 passed, 0 failed)
- ❌ 检索评测集未建立

## Codex 验收请求

READY_FOR_CODEX_PHASE_2_REAUDIT
