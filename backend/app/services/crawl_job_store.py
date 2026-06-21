"""采集任务持久化服务

Phase 2 — 将采集任务记录写入 crawl_jobs / crawl_job_items 表，
替代 sync_scheduler 的 in-memory _history / _case_history。

SQLite 和 PostgreSQL 兼容。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.crawl_job import CrawlJob, CrawlJobItem

logger = logging.getLogger(__name__)


class CrawlJobStore:
    """采集任务持久化存储"""

    @staticmethod
    def create_job(
        db: Session,
        job_type: str = "case_scrape",
        trigger_type: str = "manual",
        created_by: Optional[int] = None,
    ) -> CrawlJob:
        """创建新的采集任务记录"""
        job = CrawlJob(
            job_type=job_type,
            trigger_type=trigger_type,
            status="running",
            started_at=datetime.now(timezone.utc),
            created_by=created_by,
        )
        db.add(job)
        db.flush()
        return job

    @staticmethod
    def create_item(
        db: Session,
        job_id: int,
        source_name: str,
        source_type: str = "http",
    ) -> CrawlJobItem:
        """创建来源采集明细记录"""
        item = CrawlJobItem(
            job_id=job_id,
            source_name=source_name,
            source_type=source_type,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(item)
        db.flush()
        return item

    @staticmethod
    def complete_item(
        db: Session,
        item: CrawlJobItem,
        status: str,
        fetched_count: int = 0,
        saved_count: int = 0,
        duplicate_count: int = 0,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """完成来源采集明细"""
        item.status = status
        item.fetched_count = fetched_count
        item.saved_count = saved_count
        item.duplicate_count = duplicate_count
        item.finished_at = datetime.now(timezone.utc)
        if item.started_at:
            start = item.started_at
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            item.duration_ms = int(
                (item.finished_at - start).total_seconds() * 1000
            )
        if error_type:
            item.error_type = error_type
        if error_message:
            item.error_message = error_message

    @staticmethod
    def complete_job(
        db: Session,
        job: CrawlJob,
        status: str,
        items: list[CrawlJobItem],
        error_message: Optional[str] = None,
        kg_synced: int = 0,
    ) -> None:
        """完成采集任务 — 根据各来源明细汇总统计"""
        job.status = status
        job.finished_at = datetime.now(timezone.utc)
        job.total_sources = len(items)
        job.successful_sources = sum(1 for i in items if i.status == "success")
        job.failed_sources = sum(1 for i in items if i.status == "failed")
        job.total_fetched = sum(i.fetched_count for i in items)
        job.total_saved = sum(i.saved_count for i in items)
        job.total_duplicates = sum(i.duplicate_count for i in items)
        job.kg_synced = kg_synced
        if error_message:
            job.error_message = error_message

        # 构建 totals_json
        totals = {}
        for item in items:
            totals[item.source_name] = {
                "status": item.status,
                "fetched": item.fetched_count,
                "saved": item.saved_count,
                "duplicates": item.duplicate_count,
                "error_type": item.error_type,
                "duration_ms": item.duration_ms,
            }
        job.totals_json = json.dumps(totals, ensure_ascii=False)

    @staticmethod
    def get_recent_jobs(
        db: Session,
        limit: int = 10,
        job_type: Optional[str] = None,
    ) -> list[CrawlJob]:
        """查询最近的任务"""
        q = db.query(CrawlJob)
        if job_type:
            q = q.filter(CrawlJob.job_type == job_type)
        q = q.order_by(CrawlJob.created_at.desc()).limit(limit)
        return q.all()

    @staticmethod
    def get_job_items(db: Session, job_id: int) -> list[CrawlJobItem]:
        """查询任务的来源明细"""
        return db.query(CrawlJobItem).filter(
            CrawlJobItem.job_id == job_id
        ).order_by(CrawlJobItem.source_name).all()

    @staticmethod
    def get_last_scrape_status(db: Session, is_admin: bool = False) -> dict:
        """获取最近一次采集的摘要（供 /api/crawler/status 使用）

        普通用户只看到计数，不暴露底层错误详情。
        """
        last_job = db.query(CrawlJob).filter(
            CrawlJob.job_type == "case_scrape"
        ).order_by(CrawlJob.created_at.desc()).first()

        if not last_job:
            return {"last_scrape": None}

        items = CrawlJobStore.get_job_items(db, last_job.id)
        per_source = {}
        for item in items:
            per_source[item.source_name] = {
                "status": item.status,
                "saved": item.saved_count,
                "fetched": item.fetched_count,
                "duplicates": item.duplicate_count,
                "duration_ms": item.duration_ms,
            }
            # 仅管理员可看错误类型和错误正文（partial 和 failed 均可看）
            if is_admin:
                per_source[item.source_name]["error_type"] = item.error_type
                per_source[item.source_name]["error_message"] = (
                    item.error_message if item.status in ("failed", "partial") else None
                )

        result = {
            "last_scrape": {
                "id": last_job.id,
                "status": last_job.status,
                "trigger_type": last_job.trigger_type,
                "started_at": last_job.started_at.isoformat() if last_job.started_at else None,
                "finished_at": last_job.finished_at.isoformat() if last_job.finished_at else None,
                "total_saved": last_job.total_saved,
                "total_fetched": last_job.total_fetched,
                "total_duplicates": last_job.total_duplicates,
                "kg_synced": last_job.kg_synced,
                "per_source": per_source,
            }
        }
        if is_admin:
            result["last_scrape"]["error_message"] = last_job.error_message
        return result

    @staticmethod
    def get_job_detail(db: Session, job_id: int, is_admin: bool = False) -> dict | None:
        """获取任务详情（管理员看完整错误，普通用户只看摘要）"""
        job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
        if not job:
            return None

        items = CrawlJobStore.get_job_items(db, job_id)
        job_dict = {
            "id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "trigger_type": job.trigger_type,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "retry_count": job.retry_count,
            "total_sources": job.total_sources,
            "successful_sources": job.successful_sources,
            "failed_sources": job.failed_sources,
            "total_fetched": job.total_fetched,
            "total_saved": job.total_saved,
            "total_duplicates": job.total_duplicates,
            "kg_synced": job.kg_synced,
            "created_at": job.created_at.isoformat() if job.created_at else None,
        }

        if is_admin:
            job_dict["error_message"] = job.error_message
        else:
            # 普通用户只看到成功/失败计数，不暴露错误正文
            job_dict["error_message"] = None

        job_dict["items"] = [
            {
                "source_name": item.source_name,
                "source_type": item.source_type,
                "status": item.status,
                "fetched_count": item.fetched_count,
                "saved_count": item.saved_count,
                "duplicate_count": item.duplicate_count,
                "error_type": item.error_type,
                "error_message": item.error_message if is_admin else None,
                "duration_ms": item.duration_ms,
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "finished_at": item.finished_at.isoformat() if item.finished_at else None,
            }
            for item in items
        ]

        return job_dict


# 模块级单例
crawl_job_store = CrawlJobStore()
