"""同步调度器

功能：
1. 定时同步（默认每天凌晨 2:00）
2. 同步失败自动重试（最多 3 次）
3. 同步结果通知（日志 + 回调钩子）
4. 手动触发同步
5. 同步状态追踪
6. Phase 2: 统一状态聚合 + 持久化来源健康
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from app.services.rule_sync import rule_sync_service, rule_version_manager, SyncResult
from app.core.config import settings as app_settings

logger = logging.getLogger(__name__)


class SyncStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class SyncTaskRecord:
    """单次同步任务记录"""
    id: str = ""
    platform: str = ""
    status: SyncStatus = SyncStatus.IDLE
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result: Optional[SyncResult] = None
    error_message: str = ""
    retry_count: int = 0
    version_created: str = ""
    # 案例采集专用摘要字段
    scrape_stats: Optional[dict] = None  # crawl_all() 返回值


# ── 通知回调类型 ────────────────────────────────────────────

OnSyncCallback = Callable[[SyncTaskRecord], None]

# 所有采集来源
_ALL_SOURCES = ("ccgp", "ningxia", "shaanxi", "mof")


# ── 本地脱敏函数（避免循环导入依赖 crawler_service）──────────

def _safe_error_log(message: str) -> str:
    """截断 + 脱敏，用于日志安全输出。

    与 crawler_service._safe_error_summary 保持相同的脱敏覆盖，
    但独立定义以避免模块级循环导入。
    """
    import re
    cleaned = str(message)
    patterns = [
        # Authorization: Bearer TOKEN / Authorization=Bearer TOKEN
        (r'(?:Authorization|Auth)\s*[=:]\s*Bearer\s+\S+', '[REDACTED]'),
        # Authorization: Basic BASE64
        (r'(?:Authorization|Auth)\s*[=:]\s*Basic\s+\S+', '[REDACTED]'),
        # Bearer TOKEN (standalone)
        (r'\bBearer\s+[\w\-\.\+/]+', 'Bearer [REDACTED]'),
        # Token: VALUE / Token=VALUE
        (r'\b(?:Token|access_token|refresh_token)\s*[=:]\s*\S+', '[REDACTED]'),
        # api_key=VALUE / api-key: VALUE
        (r'\bapi[_-]?key\s*[=:]\s*\S+', '[REDACTED]'),
        # client_secret=VALUE (OAuth)
        (r'\bclient[_-]?secret\s*[=:]\s*\S+', '[REDACTED]'),
        # secret=VALUE (standalone)
        (r'\bsecret\s*[=:]\s*\S+', '[REDACTED]'),
        # password=VALUE
        (r'\bpassword\s*[=:]\s*\S+', '[REDACTED]'),
        # Cookie: ... / Set-Cookie: ... (整行脱敏)
        (r'(?:Cookie|Set-Cookie)\s*[=:]\s*.+?(?:\r?\n|$)', '[REDACTED]'),
        # URL query 中的 token/key/password/secret/signature/client_secret=VALUE
        (r'(?:[?&])(token|key|password|secret|signature|sig|client_secret)=[^&\s]+', r'?\1=[REDACTED]'),
    ]
    for pat, replacement in patterns:
        cleaned = re.sub(pat, replacement, cleaned, flags=re.IGNORECASE)
    if len(cleaned) > 2000:
        cleaned = cleaned[:2000] + "..."
    return cleaned


class SyncScheduler:
    """
    规则同步调度器。

    使用方式::

        scheduler = SyncScheduler()
        await scheduler.start()           # 启动后台定时任务
        result = await scheduler.sync("广东省公共资源交易平台")  # 手动触发

        # 停止调度
        await scheduler.stop()
    """

    def __init__(
        self,
        sync_interval_hours: int = 24,
        max_retries: int = 3,
        on_sync_complete: Optional[OnSyncCallback] = None,
        case_scrape_interval_hours: int = 168,
    ):
        self.sync_interval_hours = sync_interval_hours
        self.max_retries = max_retries
        self.on_sync_complete = on_sync_complete
        self.case_scrape_interval_hours = case_scrape_interval_hours

        self._task: Optional[asyncio.Task] = None
        self._case_task: Optional[asyncio.Task] = None
        self._running = False
        self._history: list[SyncTaskRecord] = []
        self._case_history: list[SyncTaskRecord] = []
        self._max_history = 50

    # ── 生命周期 ─────────────────────────────────────────

    async def start(self) -> None:
        """启动后台定时调度任务"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "同步调度器已启动（间隔 %d 小时，最大重试 %d 次）",
            self.sync_interval_hours, self.max_retries,
        )
        if app_settings.case_scrape_enabled:
            self._case_task = asyncio.create_task(self._run_case_scrape_loop())
            logger.info("案例采集循环已启动（间隔 %d 小时）", self.case_scrape_interval_hours)

    async def stop(self) -> None:
        """停止定时调度"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._case_task:
            self._case_task.cancel()
            try:
                await self._case_task
            except asyncio.CancelledError:
                pass
            self._case_task = None
        logger.info("同步调度器已停止")

    async def _run_loop(self) -> None:
        """后台循环：按间隔执行规则同步"""
        while self._running:
            try:
                await asyncio.sleep(self.sync_interval_hours * 3600)
                if not self._running:
                    break
                platforms = rule_sync_service.get_platforms()
                for platform in platforms:
                    if not self._running:
                        break
                    await self.sync(platform)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("定时同步异常: %s", _safe_error_log(str(e)))

    async def _run_case_scrape_loop(self) -> None:
        """后台循环：按间隔执行案例采集，每次创建独立 DB 会话持久化任务。"""
        from app.db.database import SessionLocal

        while self._running:
            try:
                await asyncio.sleep(self.case_scrape_interval_hours * 3600)
                if not self._running:
                    break
                # C-1: 创建独立、短生命周期数据库会话
                db_session = SessionLocal()
                try:
                    await self.scrape_cases(
                        db_session=db_session,
                        user_id=None,
                        trigger="scheduled",
                    )
                finally:
                    db_session.close()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("案例采集异常: %s", _safe_error_log(str(e)))

    async def scrape_cases(self, db_session=None, user_id: int | None = None, trigger: str = "manual") -> SyncTaskRecord:
        """执行一轮案例采集，成果持久化至 crawl_jobs / crawl_job_items。

        如果未提供 db_session，只写在内存 history（向后兼容）。

        Phase 2: 统一状态聚合 + 持久化来源健康。
        """
        from app.services.crawler_service import crawl_all, _ALL_SOURCES
        from app.services.crawl_job_store import crawl_job_store
        from app.services.task_status_aggregator import aggregate_job_status
        from app.services.crawler_service import _safe_error_summary

        record = SyncTaskRecord(
            id=self._next_id(),
            platform="crawler",
            status=SyncStatus.RUNNING,
            started_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )

        # ── 持久化：创建任务和明细 ──
        db_job = None
        db_items: dict[str, Any] = {}

        if db_session:
            db_job = crawl_job_store.create_job(
                db_session,
                job_type="case_scrape",
                trigger_type=trigger,
                created_by=user_id,
            )
            for src in _ALL_SOURCES:
                db_items[src] = crawl_job_store.create_item(db_session, db_job.id, src)
            db_session.commit()

        try:
            stats = await crawl_all()

            # ── 持久化各来源明细 ──────────────────────────
            if db_session and db_job:
                for src_key in _ALL_SOURCES:
                    item = db_items[src_key]
                    src_stat = stats.get(src_key, {})

                    if isinstance(src_stat, dict):
                        src_fetched = src_stat.get("fetched", 0)
                        src_saved = src_stat.get("saved", 0)
                        src_dups = src_stat.get("duplicates", 0)
                        src_errors = src_stat.get("errors", [])
                        src_error_type = src_stat.get("error_type")
                        src_error_message = src_stat.get("error_message")

                        # 使用统一来源状态规则
                        # errors 非空且 status=success → 修正为 partial
                        src_status = src_stat.get("status", "success")
                        if src_errors and src_status == "success":
                            src_status = "partial"
                            src_error_type = src_error_type or "item_errors"
                            src_error_message = src_error_message or _safe_error_summary(
                                "; ".join(str(e) for e in src_errors[:3])
                            )

                        crawl_job_store.complete_item(
                            db_session, item,
                            status=src_status,
                            fetched_count=src_fetched,
                            saved_count=src_saved,
                            duplicate_count=src_dups,
                            error_type=src_error_type,
                            error_message=src_error_message,
                        )
                    else:
                        # 向后兼容：int 类型 → 视为 success
                        src_saved = src_stat if isinstance(src_stat, int) else 0
                        crawl_job_store.complete_item(
                            db_session, item,
                            status="success",
                            fetched_count=src_saved,
                            saved_count=src_saved,
                            duplicate_count=0,
                        )

                db_session.flush()

                # ── 统一任务状态聚合（唯一入口）─────────────
                # 提取全局错误（如 kg_sync 失败）
                task_errors = [
                    e for e in stats.get("errors", [])
                    if isinstance(e, str) and ("kg_sync:" in e or "kg_sync " in e.lower())
                ]
                item_statuses = [i.status for i in db_items.values()]
                total_saved = stats.get("cases_saved", 0)
                job_status_str = aggregate_job_status(
                    item_statuses, task_errors=task_errors, total_saved=total_saved)
                record.status = SyncStatus(job_status_str)

                # 顶级错误摘要写入 crawl_jobs.error_message（脱敏+限长）
                job_error_msg = None
                global_errors = [e for e in stats.get("errors", [])
                                 if not isinstance(e, str) or ("kg_sync:" not in e and "kg_sync " not in e.lower())]
                if task_errors and job_status_str == "partial":
                    job_error_msg = _safe_error_summary("; ".join(str(e) for e in task_errors[:3]))
                    if len(job_error_msg) > 500:
                        job_error_msg = job_error_msg[:500]

                crawl_job_store.complete_job(
                    db_session, db_job,
                    status=job_status_str,
                    items=list(db_items.values()),
                    error_message=job_error_msg,
                    kg_synced=stats.get("kg_synced", 0),
                )

                # ── 更新来源健康记录 ──────────────────────
                _update_source_health_from_stats(db_session, stats)

                db_session.commit()

            else:
                # 无 db_session：仅内存状态（使用同一个聚合函数）
                src_statuses = []
                for src_key in _ALL_SOURCES:
                    s = stats.get(src_key, {})
                    st = s.get("status", "success") if isinstance(s, dict) else "success"
                    src_statuses.append(st)
                # 提取全局错误（kg_sync 等）传入聚合
                task_errors = [
                    e for e in stats.get("errors", [])
                    if isinstance(e, str) and ("kg_sync:" in e or "kg_sync " in e.lower())
                ]
                total_saved = stats.get("cases_saved", 0)
                record.status = SyncStatus(aggregate_job_status(
                    src_statuses, task_errors=task_errors, total_saved=total_saved))

            # 记录结果摘要
            record.result = SyncResult(
                new_rules=0,
                updated_rules=0,
                errors=stats.get("errors", []),
            )
            record.scrape_stats = {
                "ccgp": stats["ccgp"]["saved"] if isinstance(stats.get("ccgp"), dict) else stats.get("ccgp", 0),
                "ningxia": stats["ningxia"]["saved"] if isinstance(stats.get("ningxia"), dict) else stats.get("ningxia", 0),
                "shaanxi": stats["shaanxi"]["saved"] if isinstance(stats.get("shaanxi"), dict) else stats.get("shaanxi", 0),
                "mof": stats["mof"]["saved"] if isinstance(stats.get("mof"), dict) else stats.get("mof", 0),
                "cases_saved": stats.get("cases_saved", 0),
                "kg_synced": stats.get("kg_synced", 0),
            }

            logger.info(
                "案例采集完成: status=%s CCGP=%d 宁夏=%d 陕西=%d 财政部=%d 总保存=%d KG同步=%d",
                record.status.value,
                record.scrape_stats["ccgp"],
                record.scrape_stats["ningxia"],
                record.scrape_stats["shaanxi"],
                record.scrape_stats["mof"],
                record.scrape_stats["cases_saved"],
                record.scrape_stats["kg_synced"],
            )
        except Exception as e:
            safe_msg = _safe_error_summary(str(e))
            record.status = SyncStatus.FAILED
            record.error_message = safe_msg
            logger.error("案例采集失败: %s", safe_msg)

            # ── 失败也持久化 ──
            if db_session and db_job:
                for item in db_items.values():
                    if item.status == "running":
                        crawl_job_store.complete_item(
                            db_session, item,
                            status="failed",
                            error_type="task_error",
                            error_message=safe_msg,
                        )
                crawl_job_store.complete_job(
                    db_session, db_job,
                    status="failed",
                    items=list(db_items.values()),
                    error_message=safe_msg,
                )
                # 更新来源健康：全部标记为 failed
                for src_key in _ALL_SOURCES:
                    _update_single_source_health(db_session, src_key, "failed", error_type="task_error", error_message=safe_msg)
                db_session.commit()

        record.finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self._case_history.append(record)
        if len(self._case_history) > self._max_history:
            self._case_history.pop(0)
        return record

    # ── 手动同步 ─────────────────────────────────────────

    async def sync(self, platform: str) -> SyncTaskRecord:
        """
        对指定平台执行一次同步（含重试）。

        Args:
            platform: 平台名称

        Returns:
            SyncTaskRecord
        """
        record = SyncTaskRecord(
            id=self._next_id(),
            platform=platform,
            status=SyncStatus.RUNNING,
            started_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )

        for attempt in range(1, self.max_retries + 1):
            result = rule_sync_service.sync_from_platform(platform)

            if not result.errors:
                record.status = SyncStatus.SUCCESS
                record.result = result
                record.retry_count = attempt - 1

                version = rule_version_manager.snapshot(
                    change_log=f"同步 {platform} — "
                    f"新增{result.new_rules} 更新{result.updated_rules}"
                )
                record.version_created = version
                break

            elif attempt < self.max_retries:
                safe_errors = _safe_error_log("; ".join(result.errors))
                logger.warning(
                    "同步 %s 失败 (attempt %d/%d): %s",
                    platform, attempt, self.max_retries,
                    safe_errors,
                )
                await asyncio.sleep(2 ** attempt)

            else:
                record.status = SyncStatus.FAILED
                record.result = result
                record.error_message = _safe_error_log("; ".join(result.errors))
                record.retry_count = attempt - 1

        record.finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        if record.status == SyncStatus.SUCCESS and record.result:
            if record.result.errors:
                record.status = SyncStatus.PARTIAL
            elif record.result.new_rules == 0 and record.result.updated_rules == 0:
                record.status = SyncStatus.SUCCESS

        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        if self.on_sync_complete:
            try:
                self.on_sync_complete(record)
            except Exception as e:
                logger.error("同步通知回调失败: %s", _safe_error_log(str(e)))

        logger.info(
            "同步 %s: %s (新增%d 更新%d 错误%d)",
            platform, record.status.value,
            (record.result.new_rules if record.result else 0),
            (record.result.updated_rules if record.result else 0),
            len(record.result.errors) if record.result else 0,
        )

        return record

    # ── 状态查询 ─────────────────────────────────────────

    def get_status(self, db_session=None) -> dict:
        """调度器整体状态 — Phase 2：优先从 DB 读取最近任务"""
        running = self._running and any(
            r.status == SyncStatus.RUNNING for r in self._history[-5:]
        )
        last_sync = self._history[-1] if self._history else None

        # Phase 2：优先从 DB 读取最近采集状态
        last_case_summary = None
        if db_session:
            try:
                from app.services.crawl_job_store import crawl_job_store
                db_status = crawl_job_store.get_last_scrape_status(db_session)
                last_scrape = db_status.get("last_scrape")
                if last_scrape:
                    last_case_summary = {
                        "status": last_scrape["status"],
                        "time": last_scrape["finished_at"],
                        "error": last_scrape.get("error_message"),
                        "id": last_scrape["id"],
                        "total_saved": last_scrape.get("total_saved", 0),
                        "per_source": last_scrape.get("per_source", {}),
                    }
                    if last_scrape.get("kg_synced"):
                        last_case_summary["kg_synced"] = last_scrape["kg_synced"]
            except Exception:
                pass

        # 回退到内存历史
        if not last_case_summary:
            last_case = self._case_history[-1] if self._case_history else None
            if last_case:
                last_case_summary = {
                    "status": last_case.status.value,
                    "time": last_case.finished_at,
                    "error": last_case.error_message,
                    "id": last_case.id,
                }
                if last_case.scrape_stats:
                    last_case_summary["scrape_stats"] = last_case.scrape_stats
                if last_case.result and last_case.result.errors:
                    last_case_summary["errors"] = last_case.result.errors

        # Phase 1：依赖健康度检查
        health = _check_crawler_health()

        return {
            "running": self._running,
            "actively_syncing": running,
            "total_syncs": len(self._history),
            "last_sync": {
                "platform": last_sync.platform,
                "status": last_sync.status.value,
                "time": last_sync.finished_at,
            } if last_sync else None,
            "sync_interval_hours": self.sync_interval_hours,
            "case_scrape_enabled": app_settings.case_scrape_enabled,
            "case_scrape_interval_hours": self.case_scrape_interval_hours,
            "last_case_scrape": last_case_summary,
            "health": health,
        }

    def get_history(self, n: int = 10) -> list[dict]:
        """获取最近 N 次同步记录"""
        return [
            {
                "id": r.id,
                "platform": r.platform,
                "status": r.status.value,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "new_rules": r.result.new_rules if r.result else 0,
                "updated_rules": r.result.updated_rules if r.result else 0,
                "errors": r.result.errors if r.result else [],
                "retry_count": r.retry_count,
                "version": r.version_created,
            }
            for r in self._history[-n:][::-1]
        ]

    # ── 工具 ─────────────────────────────────────────────

    def _next_id(self) -> str:
        return f"SYNC-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{len(self._history)}"


# 模块级单例
sync_scheduler = SyncScheduler(
    case_scrape_interval_hours=app_settings.case_scrape_interval_hours,
)


def _check_crawler_health() -> dict:
    """检查采集器依赖健康度。

    返回每个关键依赖的状态：ok / degraded / unavailable。
    仅做 import 检查，不做重 IO。
    """
    health = {}

    # Playwright / browser
    try:
        import importlib
        spec = importlib.util.find_spec("playwright")
        if spec is not None:
            health["playwright"] = "ok"
        else:
            health["playwright"] = "unavailable"
    except Exception:
        health["playwright"] = "unavailable"

    # httpx (TLS support)
    try:
        import httpx
        health["httpx_tls"] = "ok"
    except Exception:
        health["httpx_tls"] = "unavailable"

    return health


# ── 来源健康更新工具 ──────────────────────────────────────


def _update_source_health_from_stats(db_session, stats: dict) -> None:
    """从 crawl_all() 返回的 stats 更新所有来源的健康记录。"""
    from app.services.source_health_service import update_source_health, ensure_all_sources_exist

    ensure_all_sources_exist(db_session)

    for src_key in _ALL_SOURCES:
        src_stat = stats.get(src_key, {})
        if not isinstance(src_stat, dict):
            continue

        src_status = src_stat.get("status", "success")
        src_fetched = src_stat.get("fetched", 0)
        src_saved = src_stat.get("saved", 0)
        src_dups = src_stat.get("duplicates", 0)
        src_error_type = src_stat.get("error_type")
        src_error_message = src_stat.get("error_message")

        # 字段完整率：优先使用 crawler 返回的真实 completeness_rate
        # (= sum of per-item completeness / parsed_count)，而非 saved/fetched
        completeness = src_stat.get("completeness_rate")
        if completeness is None or completeness < 0:
            # 没有解析结果 → 0（不代表 100%）
            completeness = 0.0

        update_source_health(
            db_session,
            source_name=src_key,
            status=src_status,
            fetched=src_fetched,
            saved=src_saved,
            duplicates=src_dups,
            error_type=src_error_type,
            error_message=src_error_message,
            completeness=completeness,
        )


def _update_single_source_health(db_session, src_key: str, status: str, error_type: str = None, error_message: str = None) -> None:
    """更新单个来源健康为 failed 状态。"""
    from app.services.source_health_service import update_source_health, ensure_all_sources_exist

    ensure_all_sources_exist(db_session)
    update_source_health(
        db_session,
        source_name=src_key,
        status=status,
        error_type=error_type,
        error_message=error_message,
    )
