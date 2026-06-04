"""同步调度器

功能：
1. 定时同步（默认每天凌晨 2:00）
2. 同步失败自动重试（最多 3 次）
3. 同步结果通知（日志 + 回调钩子）
4. 手动触发同步
5. 同步状态追踪
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from app.services.rule_sync import rule_sync_service, rule_version_manager, SyncResult

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


# ── 通知回调类型 ────────────────────────────────────────────

OnSyncCallback = Callable[[SyncTaskRecord], None]


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
    ):
        self.sync_interval_hours = sync_interval_hours
        self.max_retries = max_retries
        self.on_sync_complete = on_sync_complete

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._history: list[SyncTaskRecord] = []
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
        logger.info("同步调度器已停止")

    async def _run_loop(self) -> None:
        """后台循环：按间隔执行同步"""
        while self._running:
            try:
                # 凌晨 2 点执行（简化：启动后等 interval/2 首次执行）
                await asyncio.sleep(self.sync_interval_hours * 3600)

                if not self._running:
                    break

                # 对所有已配置的平台执行同步
                platforms = rule_sync_service.get_platforms()
                for platform in platforms:
                    if not self._running:
                        break
                    await self.sync(platform)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("定时同步异常: %s", e)

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
                # 同步成功
                record.status = SyncStatus.SUCCESS
                record.result = result
                record.retry_count = attempt - 1

                # 创建版本快照
                version = rule_version_manager.snapshot(
                    change_log=f"同步 {platform} — "
                    f"新增{result.new_rules} 更新{result.updated_rules}"
                )
                record.version_created = version
                break

            elif attempt < self.max_retries:
                # 有错误但还有重试次数
                logger.warning(
                    "同步 %s 失败 (attempt %d/%d): %s",
                    platform, attempt, self.max_retries,
                    "; ".join(result.errors),
                )
                await asyncio.sleep(2 ** attempt)

            else:
                # 所有重试都失败
                record.status = SyncStatus.FAILED
                record.result = result
                record.error_message = "; ".join(result.errors)
                record.retry_count = attempt - 1

        record.finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # 部分成功
        if record.status == SyncStatus.SUCCESS and record.result:
            if record.result.errors:
                record.status = SyncStatus.PARTIAL
            elif record.result.new_rules == 0 and record.result.updated_rules == 0:
                record.status = SyncStatus.SUCCESS  # 无变更也视为成功

        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        # 通知回调
        if self.on_sync_complete:
            try:
                self.on_sync_complete(record)
            except Exception as e:
                logger.error("同步通知回调失败: %s", e)

        logger.info(
            "同步 %s: %s (新增%d 更新%d 错误%d)",
            platform, record.status.value,
            (record.result.new_rules if record.result else 0),
            (record.result.updated_rules if record.result else 0),
            len(record.result.errors) if record.result else 0,
        )

        return record

    # ── 状态查询 ─────────────────────────────────────────

    def get_status(self) -> dict:
        """调度器整体状态"""
        running = self._running and any(
            r.status == SyncStatus.RUNNING for r in self._history[-5:]
        )
        last_sync = self._history[-1] if self._history else None
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
sync_scheduler = SyncScheduler()
