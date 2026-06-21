# Phase 2 Re-audit — Codex 复核审计简报

> 审计时间：2026-06-22
> 代码基线：`60cbfe9e`（`docs(phase-2): add Codex re-audit brief…`）
> 上一轮结论：`PHASE_2_REJECTED`（4 个阻塞项）
> 本轮请求：对 9 个阻塞项的修复逐一进行攻击式复现验证

## 0. 执行摘要

上一轮 Codex 审计识别出 4 个阻塞项（`BLOCK_RELEASE`）。本简报覆盖全部 4 个原始阻塞项 + 后续发现的 5 个子阻塞项，共计 9 个修复点。每个修复点均附有：

- 原始问题描述
- 修复文件与行号
- 攻击复现方法（使 Codex 能在当前代码库上直接运行）
- 新增回归测试（共 29 个）

## 1. 阻塞项矩阵

### 阻塞项 1：明细解析全部失败仍报告为 success
**文件**：`backend/app/services/crawler_service.py:151`
**原始问题**：来源状态仅由 `errors` 数组决定。parse_failed 完全不参与判定。实测 `fetched=10, parsed=0, saved=0, errors=[]` → `success`。
**修复**：新增 `_source_status(fetched, parsed_count, saved, errors)`，三路判定：

```
fetched==0                      → success
fetched>0 AND parsed_count==0   → failed  (全部解析失败)
errors 非空 AND 有产出          → partial (部分条目失败)
fetched>0 AND saved==0 AND parsed>0 → partial (全部重复)
否则                             → success
```

**攻击复现**：
```python
from app.services.crawler_service import _source_status
# 攻击场景：CCGP 列表 10 条，全部 parse_detail_html 返回 None
assert _source_status(10, 0, 0, []) == "failed"
# 攻击场景：宁夏列表 5 条，全部详情页为空
assert _source_status(5, 0, 0, []) == "failed"
```

**回归测试**：`TestParseAllFailedIsNotSuccess`（11 个测试）
```bash
uv run pytest tests/test_phase2_de.py::TestParseAllFailedIsNotSuccess -v
```

### 阻塞项 2：零有效产出且 KG 同步失败仍被判为 partial
**文件**：`backend/app/services/task_status_aggregator.py:42`
**原始问题**：`aggregate_job_status` 只检查来源状态，不检查有效产出。4 个来源自我报告 success + KG 数据库错误 → `partial`。实测 `total_saved=0` 时仍为 partial。
**修复**：新增 `total_saved` 参数。`task_errors` 非空 + `total_saved==0` → `failed`。

**攻击复现**：
```python
from app.services.task_status_aggregator import aggregate_job_status
# 攻击场景：4 success + kg_sync 错误 + 零产出
assert aggregate_job_status(
    ["success","success","success","success"],
    task_errors=["kg_sync: database unavailable"],
    total_saved=0
) == "failed"
```

**回归测试**：`TestZeroOutputPlusKgErrorIsFailed`（4 个测试）

### 阻塞项 3：敏感错误信息未在写入和日志边界统一脱敏
**文件**：`backend/app/services/crawler_service.py:483-500`（`_CREDENTIAL_PATTERNS`）、`backend/app/services/source_health_service.py:54-71`
**原始问题**：多个路径可将原始凭证写入 DB 或日志。实测 `client_secret=raw-secret`、`Authorization: Basic BASE64` 原样进入。
**修复**：
- `_CREDENTIAL_PATTERNS` 从 7 种扩展到 13 种（含 `Authorization: Basic`、`client_secret=`、独立 `secret=`)
- `source_health_service.py` 新增 `_sanitize_error_type()` / `_sanitize_error_message()`，写入 DB 前脱敏
- 所有 Exception 日志路径统一使用 `_safe_error_summary(str(e))`

**攻击复现**：
```python
from app.services.crawler_service import _safe_error_summary
# 攻击场景：client_secret 直接出现在异常消息中
cleaned = _safe_error_summary("OAuth error: client_secret=ghp_raw_123")
assert "ghp_raw_123" not in cleaned
assert "REDACTED" in cleaned
# 攻击场景：Basic Auth header
cleaned = _safe_error_summary("Auth: Basic dXNlcjpwYXNz")
assert "dXNlcjpwYXNz" not in cleaned
```

**回归测试**：`TestErrorSummaryRedaction`（13 个参数化测试）+ `TestCredentialRedactionBoundary`（7 个测试）

### 阻塞项 4：陕西全部解析失败仍报告为 success
**文件**：`backend/app/services/crawler_service.py:339-344`、`backend/app/services/browser_crawler.py:60-95`
**原始问题**：陕西段 `fetched = parsed_count`（始终 0），无条件写入 `status = "success"`。攻击复现：listed=10，详情全部返回 None → `fetched=0, status=success`，聚合后仍为 success。
**修复**：
- `browser_crawler.py`: 返回值新增 `listed`（列表页条目数）和 `parse_failed` 字段
- `crawler_service.py`: 陕西段 `fetched` 取自 `listed`（非 `parsed_count`），使用 `_source_status()`

**攻击复现**：
```python
from app.services.crawler_service import _source_status
# 攻击场景：陕西列表 10 条，详情全部失败
assert _source_status(fetched=10, parsed_count=0, saved=0, errors=[]) == "failed"
# 攻击场景：陕西列表 10 条，9 条成功、1 条失败 → partial
assert _source_status(fetched=10, parsed_count=9, saved=9, errors=["err"]) == "partial"
```

**回归测试**：`TestShaanxiParseAllFailed`（7 个测试）

### 阻塞项 5：单条明细失败导致整个来源 failed
**文件**：`backend/app/services/crawler_service.py:161`
**原始问题**：`_source_status` 将 `errors` 非空直接判定为 `failed`。抓取 10 条、成功 9 条、失败 1 条 → `failed`，应为 `partial`。
**修复**：`_source_status` 判定顺序重排 — errors 非空但仍有产出（saved>0 或 parsed>0）→ `partial`。

**攻击复现**：
```python
from app.services.crawler_service import _source_status
# 攻击场景：10 条中 1 条 detail fetch 403
assert _source_status(10, 9, 9, ["detail fetch 403"]) == "partial"
# 对比：全部失败仍是 failed
assert _source_status(10, 0, 0, ["detail fetch 403"]) == "failed"
```

**回归测试**：`test_fetched_10_parsed_9_saved_9_one_error_is_partial` 等 3 个新增

### 阻塞项 6：原始敏感异常仍可进入日志
**文件**：`backend/app/services/browser_crawler.py:54,92`、`backend/app/services/mof_crawler.py:45`、`backend/app/services/crawler_service.py:491`
**原始问题**：多处在 `logger.error("%s", e)` 中直接传入异常对象。实测 `client_secret=raw-secret` 原样写入日志。
**修复**：所有 logger 调用点统一使用 `_safe_error_summary(str(e))`。

**攻击复现**：
```bash
grep -n 'logger\.\(error\|warning\).*%s.*, e)' backend/app/services/*.py
# 应返回空（所有 raw exception logging 已替换）
```

**回归测试**：`test_exception_paths_log_safe_summary`

### 阻塞项 7：sync_scheduler.py 中 _safe_error_summary NameError
**文件**：`backend/app/services/sync_scheduler.py:143,167,424`
**原始问题**：`_safe_error_summary` 仅在 `scrape_cases()` 方法内局部导入，但 `_run_loop()` 和 `_run_case_scrape_loop()` 中的 `logger.error` 也引用了它 → `NameError` → 调度循环退出。
**修复**：新增模块级 `_safe_error_log()` 函数（自包含脱敏逻辑，无导入依赖）。`_run_loop` 中 3 处 `logger.error` 均改用 `_safe_error_log(str(e))`。

**攻击复现**：
```python
from app.services.sync_scheduler import _safe_error_log
# 无需导入 crawler_service 即可使用
cleaned = _safe_error_log("Exception: client_secret=ghp_raw_123")
assert "ghp_raw_123" not in cleaned
assert "REDACTED" in cleaned
```

**验证**：`_safe_error_log` 在 `class SyncScheduler` 之前定义，无需导入即可在模块内所有方法中使用。

### 阻塞项 8：NATL-001 被替换为无依据的新文案并放宽测试
**文件**：`rules/platform_rules.json:12`、`backend/tests/test_rule_version_integrity.py:392`
**原始问题**：之前将 NATL-001.description 从 `'E2E测试更新'` 改为 `'国家法规模板 — 禁止擅自修改法定条款'`（无依据），同时将此错误值加入 `HISTORICAL_VARIANTS` 白名单来通过测试。
**修复**：
- 恢复 `platform_rules.json` NATL-001.description → `"缺少规定章节"`（与 `rule_sync.py:82` 源代码基线一致）
- 恢复 `manifest.json` 全部 7 个版本条目
- 恢复 5 个快照文件中的描述
- 从 `HISTORICAL_VARIANTS` 移除错误值

**攻击复现**：
```python
import json
from pathlib import Path
data = json.loads(Path("rules/platform_rules.json").read_text())
for m in data["mappings"]:
    if m["rule_id"] == "NATL-001":
        assert m["description"] == "缺少规定章节", \
            f"NATL-001 should be '缺少规定章节', got '{m['description']}'"
```

**回归测试**：`test_rule_version_integrity.py` 24 个测试全部通过

### 阻塞项 9：状态文档与实际结果不一致
**文件**：`docs/case-library/CURRENT_STATUS.md`
**原始问题**：多个数据点不准确 — Git HEAD、测试计数、规则 manifest 哈希。
**修复**：根据实际命令输出重写，所有数字由 `git log`、`pytest`、`shasum`、`gh run view` 即时生成。

## 2. 非功能性修复

### CI Flaky 测试修复（5 个提交）
`test_production_docs_disabled` 在 GitHub Actions 中长期失败。根因诊断链：
1. stderr PIPE 捕获 → `error: Failed to initialize cache at /private/tmp/uv-cache: Permission denied`
2. `UV_CACHE_DIR` 回退链改为 `XDG_CACHE_HOME` → `~/.cache/uv`
3. `_UV_BIN` 改为 `shutil.which("uv")` with fallback

同样修复应用于 `test_production_config.py`。

### 规则资产清理（4 个提交）
- 61 条 TEST-AUDIT/UUID 规则从 `platform_rules.json` 移除
- 从 `manifest.json`（7 个版本条目去重）和 28 个快照文件移除
- Monkeypatch 加固：`RuleSyncService._save` 类级补丁
- Conftest 迁移警告抑制

## 3. 验证检查清单

Codex 审计员请逐项执行：

- [ ] `uv run pytest tests/test_phase2_de.py -v` — 99 passed
- [ ] `uv run pytest tests/test_rule_version_integrity.py -v` — 24 passed
- [ ] `uv run pytest tests/test_source_fixtures.py -v` — 18 passed
- [ ] `uv run pytest tests/security/test_fastapi_security_baseline.py tests/security/test_production_config.py tests/security/test_rules_admin_audit.py tests/security/test_phase1_safety.py -v` — 全部通过
- [ ] `grep -rn 'logger\.\(error\|warning\).*%s.*, e)' backend/app/services/` — 空
- [ ] `grep -rn '_safe_error_summary' backend/app/services/sync_scheduler.py | head -5` — 检查 `_run_loop` 内的 logger 调用使用 `_safe_error_log` 而非 `_safe_error_summary`
- [ ] `python3 -c "import json; d=json.load(open('rules/platform_rules.json')); assert next(m for m in d['mappings'] if m['rule_id']=='NATL-001')['description']=='缺少规定章节'"` — 通过
- [ ] GH Actions 最近一次 CI：`conclusion: success`，0 failed
- [ ] `git status --short` — clean
- [ ] `grep -rn 'parse_all_failed' backend/app/services/crawler_service.py` — 显示 error_type 在 `_source_status` 返回 failed 后正确设置

## 4. 变更文件清单

```
backend/app/services/crawler_service.py        # _source_status + 日志脱敏
backend/app/services/task_status_aggregator.py  # total_saved 参数
backend/app/services/source_health_service.py   # 写入前脱敏
backend/app/services/sync_scheduler.py          # _safe_error_log + 日志
backend/app/services/browser_crawler.py         # listed/parse_failed
backend/app/services/mof_crawler.py             # 日志脱敏
backend/tests/test_phase2_de.py                 # 29 个新增回归测试
backend/tests/test_rule_version_integrity.py    # NATL-001 规范基线恢复
backend/tests/security/test_fastapi_security_baseline.py  # CI flaky 修复
backend/tests/security/test_production_config.py          # CI flaky 修复
backend/tests/security/test_rules_admin_audit.py          # monkeypatch 加固
backend/tests/conftest.py                       # 迁移警告抑制
rules/platform_rules.json                       # 测试污染清理 + NATL-001
rules/versions/manifest.json                    # 去重 + 污染清理 + NATL-001
rules/versions/rules_*.json (28 files)          # 污染清理 + NATL-001
docs/case-library/CURRENT_STATUS.md             # 状态文档重写
```

## Codex 验收请求

`READY_FOR_CODEX_PHASE_2_REAUDIT`
