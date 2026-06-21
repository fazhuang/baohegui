"""采集来源健康状态模型

Phase 2 — 持久化运行时来源健康状态：
- crawl_source_health: 每个来源的运行统计和健康状态
- 替代静态 canary_config.json fixture 文件
- 每轮真实采集完成后更新
- 服务重启后状态持久化

Phase 2 re-audit:
- 增加连续覆盖天数字段，不靠首末时间推断连续运行
- 每日运行记录通过 daily_health_snapshot 表跟踪
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, Date

from app.models.document import Base


class CrawlSourceHealth(Base):
    """采集来源运行时健康状态"""

    __tablename__ = "crawl_source_health"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_name = Column(
        String(64), nullable=False, unique=True, index=True,
        comment="来源名称: ccgp/ningxia/shaanxi/mof",
    )

    # ── 运行时间线 ────────────────────────────────────
    first_run_at = Column(DateTime, nullable=True, comment="首次运行时间")
    last_run_at = Column(DateTime, nullable=True, comment="最近一次运行时间")
    last_success_at = Column(DateTime, nullable=True, comment="最近一次成功时间")
    last_success_date = Column(Date, nullable=True, comment="最近一次成功日期（自然日）")

    # ── 计数器 ─────────────────────────────────────────
    consecutive_failures = Column(Integer, default=0, comment="连续失败次数")
    consecutive_success_days = Column(Integer, default=0, comment="连续成功天数")
    observed_days = Column(Integer, default=0, comment="实际观测到的有效运行天数")
    total_runs = Column(Integer, default=0, comment="总运行次数")
    successful_runs = Column(Integer, default=0, comment="成功运行次数")

    # ── 最近一次运行状态 ──────────────────────────────
    last_status = Column(String(16), nullable=True, comment="最近一次运行状态: success/partial/failed")

    # ── 产出统计 ──────────────────────────────────────
    fetched_count = Column(Integer, default=0, comment="累计抓取条目数")
    saved_count = Column(Integer, default=0, comment="累计保存案例数")
    duplicate_count = Column(Integer, default=0, comment="累计重复数")

    # ── 质量指标 ──────────────────────────────────────
    completeness_rate = Column(
        Float, default=0.0, nullable=False,
        comment="必填字段完整率 (0.0–1.0)，由实际解析字段计算",
    )

    # ── 最近错误 ──────────────────────────────────────
    last_error_type = Column(String(64), nullable=True, comment="最近错误类型")
    last_error_message = Column(Text, nullable=True, comment="最近错误描述（脱敏）")

    # ── 健康状态 ──────────────────────────────────────
    health_status = Column(
        String(32), nullable=False, default="collecting",
        comment="健康状态: collecting/not_enough_data/healthy/degraded/failed",
    )

    updated_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="记录更新时间",
    )

    def to_dict(self, is_admin: bool = False) -> dict:
        """转为 API 响应的 dict。

        管理员可见错误摘要，普通用户不可见。
        """
        d = {
            "source_name": self.source_name,
            "first_run_at": self.first_run_at.isoformat() if self.first_run_at else None,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_success_date": self.last_success_date.isoformat() if self.last_success_date else None,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_success_days": self.consecutive_success_days,
            "observed_days": self.observed_days,
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "last_status": self.last_status,
            "fetched_count": self.fetched_count,
            "saved_count": self.saved_count,
            "duplicate_count": self.duplicate_count,
            "completeness_rate": round(self.completeness_rate, 4),
            "health_status": self.health_status,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if is_admin:
            d["last_error_type"] = self.last_error_type
            d["last_error_message"] = self.last_error_message
        return d


class DailyHealthSnapshot(Base):
    """每日健康快照 — 记录每个来源每天的运行情况

    用于准确判断连续 N 天有效运行，不靠首末时间推断。
    """

    __tablename__ = "daily_health_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_name = Column(String(64), nullable=False, comment="来源名称")
    snapshot_date = Column(Date, nullable=False, comment="快照日期（自然日）")
    status = Column(String(16), nullable=False, default="success", comment="当日状态")
    runs = Column(Integer, default=0, comment="当日运行次数")
    fetched = Column(Integer, default=0, comment="当日抓取数")
    saved = Column(Integer, default=0, comment="当日保存数")
    completeness = Column(Float, default=0.0, comment="当日字段完整率")
    error_type = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
    )
