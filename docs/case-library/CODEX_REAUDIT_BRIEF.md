# Phase 2 Re-audit — Codex 复核审计简报

> 审计时间：2026-06-23 12:00 CST
> 代码基线：`a32032d0`（`docs(phase-2): update CURRENT_STATUS.md — 15 blockers fixed, HEAD=dffba4e0`）
> 上一轮结论：`PHASE_2_REJECTED`（2 个阻塞项）
> 本轮请求：对 15 个阻塞项的修复逐一进行攻击式复现验证
> 修复证据文件：`docs/case-library/CODEX_REAUDIT_BRIEF.md`（本文件）
> 状态摘要文件：`docs/case-library/CURRENT_STATUS.md`
> 审计上下文：`docs/case-library/PHASE_0_CODEX_AUDIT.md`、`docs/case-library/PHASE_1_AUDIT_REPORT.md`

## 0. 执行摘要

Phase 2 共经历三轮 Codex re-audit，累计修复 15 个阻塞项：

| 轮次 | 阻塞项数 | 提交序列 | 结论 |
|---|---|---|---|
| 第一轮 | 9 | `8d39f3e5` … `375648c9` | `PHASE_2_REJECTED`（4 个新阻塞项） |
| 第二轮 | 4 | `52917f2a` | `PHASE_2_REJECTED`（2 个新阻塞项） |
| 第三轮 | 2 | `dffba4e0` | **待审** |

每轮修复均附有攻击复现方法和新建回归测试。

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

## 2. 第二轮修复（4 个阻塞项，`52917f2a`）

### 阻塞项 10：sync_scheduler._safe_error_log 脱敏正则不完整 + sync() raw errors 未脱敏
**文件**：`backend/app/services/sync_scheduler.py:62-80,434-445`
**原始问题**：`_safe_error_log` 仅覆盖 8 种模式（缺 Cookie/Set-Cookie 行脱敏和 URL query 参数脱敏），且 `sync()` 方法直接将 `result.errors` 传入 `logger.warning` 和 `record.error_message`。
**修复**：`_safe_error_log` 正则集与 `crawler_service._CREDENTIAL_PATTERNS` 对齐（13 种模式）；`sync()` 中 2 处 raw `result.errors` 经 `_safe_error_log` 脱敏。

**攻击复现**：
```bash
grep -c "Set-Cookie\|\\\?.*=" backend/app/services/sync_scheduler.py::_safe_error_log
# _safe_error_log 应覆盖 Cookie 和 URL 参数模式
```

### 阻塞项 11：SafeFetchError.message 嵌入原始异常绕过脱敏
**文件**：`backend/app/services/safe_fetcher.py:134,364,382,387`、`backend/app/services/crawler_service.py:243,265,299,320,392,414`
**原始问题**：`safe_fetcher.py` 4 处将 raw `{e}` 嵌入 `SafeFetchError.message`，之后 `crawler_service.py` 6 处将 `e.message` 直接存入 `stats["errors"]`，全程无脱敏。
**修复**：`safe_fetcher.py` 新增 `_sanitize_exc()` 函数（13 种模式），4 处 raw `{e}` 替换为 `_sanitize_exc(str(e))`；`crawler_service.py` 6 处 `stats["errors"].append` 对 `e.message` 追加 `_safe_error_summary` 双重脱敏。

**攻击复现**：
```python
from app.services.safe_fetcher import _sanitize_exc
cleaned = _sanitize_exc("Connection failed 10.0.0.1: password=abc123")
assert "abc123" not in cleaned
assert "REDACTED" in cleaned
```

### 阻塞项 12：陕西部分解析失败仍 success（parse_failed_count 未参与判定）
**文件**：`backend/app/services/crawler_service.py:151-177`
**原始问题**：`_source_status` 签名缺少 `parse_failed_count`。`listed=10, parsed=9, parse_failed=1, errors=[]` → `"success"`。
**修复**：新增 `parse_failed_count` 参数，`fetched>0 AND parse_failed_count>0` → `"partial"`。4 个调用点全部传入。

**攻击复现**：
```python
from app.services.crawler_service import _source_status
assert _source_status(10, 9, 9, [], parse_failed_count=1) == "partial"
```

### 阻塞项 13：CURRENT_STATUS.md 基线 HEAD 不符
**文件**：`docs/case-library/CURRENT_STATUS.md`
**修复**：HEAD 修正为 `52917f2a`，规则哈希与 `shasum -a 256` 一致。

## 3. 第三轮修复（2 个阻塞项，`dffba4e0`）

### 阻塞项 14：partial 缺少降级原因（None 传播至任务明细/健康表/快照）
**文件**：`backend/app/services/crawler_service.py:266-269,330-332,369-372,431-434`、`backend/app/services/sync_scheduler.py:268-277`
**原始问题**：`parse_failed_count>0` 触发 `"partial"` 但 `errors` 为空时，`error_type`/`error_message` 保持 `None`。该 `None` 直接写入 `crawl_job_items`、`source_health` 和每日快照。
**修复**：
- `crawler_service.py`：4 个来源（CCGP/宁夏/陕西/财政部）在 `_source_status` 之后新增 `elif status=="partial" and parse_failed>0` 分支，设置 `error_type="partial_parse"` 和 `error_message="部分条目解析失败: {n}/{total}"`
- `sync_scheduler.py`：`scrape_cases()` 持久化明细时二次兜底 — 若 `status=="partial"` 且 `error_type`/`error_message` 均为空，从 `parse_failed_count` 或 `saved==0` 派生

**攻击复现**：
```python
# 模拟 crawler_service 陕西段：listed=10, parsed=9, parse_failed=1, errors=[]
# 修复前：error_type=None, error_message=None → 写入 DB
# 修复后：error_type="partial_parse", error_message="部分条目解析失败: 1/10"
```

### 阻塞项 15：CURRENT_STATUS.md 哈希失真
**文件**：`docs/case-library/CURRENT_STATUS.md`
**原始问题**：HEAD SHA 和规则资产哈希与实际值不符（写为 `4b05cf3d...` 等 git blob hash 而非 SHA-256）。
**修复**：HEAD 修正为 `dffba4e0`，规则哈希与 `shasum -a 256 rules/platform_rules.json rules/versions/manifest.json` 输出一致。

## 4. 非功能性修复

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

## 5. 验证检查清单

Codex 审计员请逐项执行：

- [ ] `git log -1 --format='%H %s'` — HEAD = `a32032d0...` (docs/phase-2: update CURRENT_STATUS.md — 15 blockers fixed)
- [ ] `uv run pytest tests/test_phase2_de.py -v` — 99 passed
- [ ] `uv run pytest tests/test_rule_version_integrity.py -v` — 24 passed
- [ ] `uv run pytest tests/test_source_fixtures.py -v` — 18 passed
- [ ] **总计：141 passed, 0 failed**
- [ ] `uv run pytest tests/security/test_fastapi_security_baseline.py tests/security/test_production_config.py tests/security/test_rules_admin_audit.py tests/security/test_phase1_safety.py -v` — 全部通过
- [ ] `grep -rn 'logger\.\(error\|warning\).*%s.*, e)$' backend/app/services/crawler_service.py backend/app/services/browser_crawler.py backend/app/services/mof_crawler.py backend/app/services/sync_scheduler.py` — 空（无 raw `e` 传入 logger）
- [ ] `grep -rn '{e}' backend/app/services/safe_fetcher.py` — 空（4 处已替换为 `_sanitize_exc(str(e))`）
- [ ] `grep -rn '_safe_error_log' backend/app/services/sync_scheduler.py` — 显示模块级函数定义 + 4 处调用
- [ ] `python3 -c "import json; d=json.load(open('rules/platform_rules.json')); assert next(m for m in d['mappings'] if m['rule_id']=='NATL-001')['description']=='缺少规定章节'"` — 通过
- [ ] `python3 -c "import json; from pathlib import Path; markers={'TEST-AUDIT','FILE-T1','UFB-3390EBC9','VR-T2','V-TEST-1','V-T3','E2E测试更新'}; raw=Path('rules/platform_rules.json').read_text(); [print(f'POLLUTED: {m}') for m in markers if m in raw]"` — 空
- [ ] `grep -rn 'partial_parse' backend/app/services/crawler_service.py` — 4 个来源均有 `elif status=="partial" and parse_failed_count>0` 分支
- [ ] `grep -rn 'partial.*error_type.*error_message' backend/app/services/sync_scheduler.py` — 二次兜底派生逻辑
- [ ] GH Actions 最近一次 CI：`conclusion: success`，0 failed
- [ ] `git status --short` — clean
- [ ] Phase 1 regression: `test_partial_on_source_error`、`test_success_when_no_errors`、`test_kg_sync_error_causes_partial` — 全部通过
- [ ] `shasum -a 256 rules/platform_rules.json rules/versions/manifest.json` — 与 CURRENT_STATUS.md 中哈希一致
- [ ] 审计简报一致性：本文件 SHA 与 git 中提交的版本一致

## 6. 变更文件清单

```
backend/app/services/crawler_service.py        # _source_status + parse_failed_count + partial_parse 分支 + 日志脱敏
backend/app/services/safe_fetcher.py            # _sanitize_exc() 新增 + 4 处 raw {e} 替换
backend/app/services/sync_scheduler.py          # _safe_error_log 正则补齐 + sync() 脱敏 + partial 兜底派生
backend/app/services/task_status_aggregator.py  # total_saved 参数
backend/app/services/source_health_service.py   # 写入前脱敏
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
docs/case-library/CURRENT_STATUS.md             # 状态文档（15 个阻塞项，141 tests）
docs/case-library/CODEX_REAUDIT_BRIEF.md        # 本文件
```

## Codex 验收请求

`READY_FOR_CODEX_PHASE_2_REAUDIT`
