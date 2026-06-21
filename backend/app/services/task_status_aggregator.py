"""统一采集任务状态聚合

Phase 2 Block A — 整个代码库中唯一决定任务状态和来源状态聚合的地方。

规则：
1. 全部来源 success + 无全局错误 + 有有效产出 → job success
2. 至少一个来源 success/partial 同时存在来源错误或全局错误 → job partial
3. 所有实际执行来源均 failed → job failed
4. KG 同步失败但案例采集有成功结果 → partial
5. KG 同步失败且没有任何有效成功结果（total_saved==0）→ failed
6. crawl_all 抛出任务级异常 → job failed
7. 没有任何执行的来源 → skipped（不在 aggregation 范围）

来源级状态判定：
- 每个来源有自己的 status (success/partial/failed/skipped)
- errors 非空且 status=success → 强制修正为 partial
- 来源级连接异常 (SafeFetchError / Exception) → failed
- 从未执行的来源 → skipped（不参与全局聚合）

全局聚合后，内存 record、数据库、API 必须使用同一最终状态。
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Sequence


class SourceStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class JobStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


def aggregate_job_status(
    source_statuses: Sequence[str],
    *,
    task_errors: Optional[list] = None,
    total_saved: int = 0,
) -> str:
    """根据各来源状态和全局错误聚合出任务级最终状态。

    这是唯一的状态聚合函数。禁止在多处独立判断。

    Args:
        source_statuses: 各来源状态列表，例如 ["success", "success", "partial", "failed"]
        task_errors: 全局/任务级错误列表（如 kg_sync 错误），非空时可能降级为 partial
        total_saved: 全量实际保存案例数。0 且存在 task_errors → failed

    Returns:
        "success" | "partial" | "failed"
    """
    if not source_statuses:
        return "failed"

    # 过滤掉 skipped 来源（未执行，不参与聚合）
    executed = [s for s in source_statuses if s != "skipped"]
    if not executed:
        return "failed"  # 所有来源都未执行 → failed

    successes = sum(1 for s in executed if s == "success")
    partials = sum(1 for s in executed if s == "partial")
    failures = sum(1 for s in executed if s == "failed")

    # 规则 3：所有执行来源均 failed
    if failures == len(executed):
        return "failed"

    # 规则 2a：至少一个 failed 或 partial → partial
    if failures > 0 or partials > 0:
        return "partial"

    # 规则 5b：全部来源 success 但零有效产出 + 存在全局/任务级错误 → failed
    # （来源抓取到了条目、但解析/保存全失败；KG 同步也失败了）
    has_errors = task_errors and len(task_errors) > 0
    if has_errors and total_saved == 0:
        return "failed"

    # 规则 4：全部来源 success，但存在全局错误 → partial
    # （如 kg_sync 失败但案例采集有成功结果）
    if has_errors:
        return "partial"

    # 规则 1+5：全部来源 success 且无全局错误 → success
    return "success"
