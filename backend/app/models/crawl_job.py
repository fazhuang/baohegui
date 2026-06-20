"""采集任务持久化模型

Phase 2 — 将采集任务和来源明细存储到数据库：
- crawl_jobs: 每次采集任务的主记录
- crawl_job_items: 每个采集源的明细结果

这些表替代了 sync_scheduler 的 in-memory _history 和 _case_history，
确保进程重启后可追溯。
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class CrawlJob(Base):
    """采集任务主记录"""

    __tablename__ = "crawl_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_type = Column(String(32), nullable=False, default="case_scrape", comment="任务类型: case_scrape")
    status = Column(
        String(16), nullable=False, default="running",
        comment="任务状态: running/success/failed/partial"
    )
    trigger_type = Column(
        String(16), nullable=False, default="manual",
        comment="触发类型: manual/scheduled/retry"
    )
    started_at = Column(DateTime, nullable=True, comment="任务开始时间")
    finished_at = Column(DateTime, nullable=True, comment="任务完成时间")
    retry_count = Column(Integer, default=0, comment="重试次数")
    error_message = Column(Text, nullable=True, comment="顶级错误信息")

    # ── 统计摘要（JSON 兼容字段，SQLite 无 JSONB）─────
    total_sources = Column(Integer, default=0, comment="总来源数")
    successful_sources = Column(Integer, default=0, comment="成功来源数")
    failed_sources = Column(Integer, default=0, comment="失败来源数")
    total_fetched = Column(Integer, default=0, comment="总抓取数")
    total_saved = Column(Integer, default=0, comment="总保存数")
    total_duplicates = Column(Integer, default=0, comment="总重复数")
    totals_json = Column(Text, nullable=True, comment="各来源详细统计 JSON")
    kg_synced = Column(Integer, default=0, comment="KG 同步数")

    created_by = Column(Integer, nullable=True, comment="触发人 user_id（manual 时有值）")
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        comment="记录创建时间"
    )


class CrawlJobItem(Base):
    """采集任务来源明细 — 每个采集源的独立结果"""

    __tablename__ = "crawl_job_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, nullable=False, index=True, comment="关联 crawl_jobs.id")

    source_name = Column(String(64), nullable=False, comment="来源名称: ccgp/ningxia/shaanxi/mof")
    source_type = Column(
        String(32), nullable=False, default="http",
        comment="来源类型: http/browser/api"
    )
    status = Column(
        String(16), nullable=False, default="running",
        comment="明细状态: running/success/failed/skipped"
    )
    fetched_count = Column(Integer, default=0, comment="抓取到的条目数")
    saved_count = Column(Integer, default=0, comment="保存到 complaint_cases 的数量")
    duplicate_count = Column(Integer, default=0, comment="重复数量")
    error_type = Column(String(64), nullable=True, comment="错误类型标签")
    error_message = Column(Text, nullable=True, comment="错误详情（仅管理员可见）")
    retry_count = Column(Integer, default=0, comment="此来源的重试次数")
    duration_ms = Column(Integer, nullable=True, comment="耗时（毫秒）")
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
    )
