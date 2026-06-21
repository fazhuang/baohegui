"""来源健康状态服务

Phase 2 Block C — 为 4 个采集来源提供持久化运行时健康追踪。

核心职责：
1. 每轮真实采集完成后更新健康记录
2. 记录每日快照 (daily_health_snapshots)，确保持续天数可证明
3. 根据连续天数、成功率、完整率计算 health_status
4. 管理员可查看脱敏错误详情；普通用户不可见

健康状态规则（集中在此函数）：
- collecting:    尚无任何运行记录 (total_runs == 0)
- not_enough_data: 实际观测天数 < 7 天（即使首次运行超过 7 天）
- healthy:       最近连续 7 个自然日均有有效运行记录 AND 最近运行 success
                  AND 成功率 ≥ 阈值 AND 完整率 ≥ 阈值 AND consecutive_failures == 0
- degraded:      当前 partial 或最近一次失败但未达 failed 阈值
                  或七日成功率/完整率下降
- failed:        当前运行是 failed 或连续失败达到阈值
                  不得因为历史成功就隐藏当前失败

硬性要求：
- 不足 7 天绝不 healthy
- 不伪造历史数据
- completeness_rate 由真实字段计算，不写固定常量
- 成功后清空 last_error_type 和 last_error_message
- partial/failed 必须更新 last_status
- 服务重启和新 Session 后连续统计仍存在（通过 DB 持久化）
"""

from __future__ import annotations

import logging
from datetime import date as date_cls
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.crawl_source_health import CrawlSourceHealth, DailyHealthSnapshot
from app.services.crawler_service import _ALL_SOURCES

logger = logging.getLogger(__name__)

# ── 阈值常量 ─────────────────────────────────────────────────

MIN_DAYS_FOR_HEALTHY = 7
SUCCESS_RATE_THRESHOLD = 0.7    # 成功率 ≥ 70%
COMPLETENESS_THRESHOLD = 0.5    # 字段完整率 ≥ 50%
MAX_CONSECUTIVE_FAILURES = 5    # ≥ 此值 → failed
WMA_ALPHA = 0.3                 # completeness 加权移动平均因子
_MAX_ERROR_TYPE_LEN = 64        # DB 列宽上限


def _sanitize_error_type(raw: str) -> str:
    """将 error_type 截断到 DB 列宽上限，移除不可打印字符。"""
    if not raw:
        return raw
    cleaned = str(raw)
    # 移除 control chars（保留 printable + unicode）
    cleaned = ''.join(c for c in cleaned if c.isprintable() or c in ('\t', '\n', '\r'))
    if len(cleaned) > _MAX_ERROR_TYPE_LEN:
        cleaned = cleaned[:_MAX_ERROR_TYPE_LEN]
    return cleaned


def _sanitize_error_message(raw: str) -> str:
    """写入 DB 前脱敏 error_message，委托 crawling_service._safe_error_summary。"""
    from app.services.crawler_service import _safe_error_summary
    if not raw:
        return raw
    return _safe_error_summary(str(raw))


# ── 唯一健康状态计算 — 集中决策 ──────────────────────────────


def compute_health_status(
    health: CrawlSourceHealth,
    *,
    now: Optional[datetime] = None,
) -> str:
    """根据持久化运行记录计算来源健康状态。

    这是整个代码库唯一决定 health_status 的函数。
    所有调用方（API、前端）必须使用此函数的结果，
    不得自行推导或使用固定常量。

    Args:
        health: CrawlSourceHealth 数据库记录
        now: 当前时间（测试注入用）

    Returns:
        "collecting" | "not_enough_data" | "healthy" | "degraded" | "failed"
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # 规则 0：无运行记录 → collecting
    if health.total_runs == 0 or health.first_run_at is None:
        return "collecting"

    # 规则 1：最近一次运行是 failed → failed / degraded
    if health.last_status == "failed":
        if health.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            return "failed"
        # 单次失败但总成功率尚可 → degraded
        if health.total_runs > 1 and health.successful_runs > 0:
            return "degraded"
        return "failed"

    # 规则 2：连续失败 ≥ MAX_CONSECUTIVE_FAILURES → failed
    if health.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        return "failed"

    # 规则 3：实际观测天数不足 7 天 → not_enough_data
    # 即使 first_run_at 超过 7 天，但只有 2 次运行、间隔 8 天，也不能 healthy
    obs_days = health.observed_days or 0
    if obs_days < MIN_DAYS_FOR_HEALTHY:
        return "not_enough_data"

    # 规则 4：最近一次运行不是 success → degraded
    if health.last_status != "success":
        return "degraded"

    # 规则 5：连续成功天数不足 7 天 → degraded
    if (health.consecutive_success_days or 0) < MIN_DAYS_FOR_HEALTHY:
        return "degraded"

    # 规则 6：成功率不足 → degraded
    success_rate = (
        health.successful_runs / health.total_runs
        if health.total_runs > 0 else 0.0
    )
    if success_rate < SUCCESS_RATE_THRESHOLD:
        return "degraded"

    # 规则 7：字段完整率不足 → degraded
    if (health.completeness_rate or 0.0) < COMPLETENESS_THRESHOLD:
        return "degraded"

    # 规则 8：consecutive_failures > 0 → degraded（不应出现在 healthy）
    if health.consecutive_failures > 0:
        return "degraded"

    # 规则 9：最近连续 7 天成功 + 成功率达标 + 完整率达标 → healthy
    return "healthy"


# ── 每日快照服务 ──────────────────────────────────────────────


def _record_daily_snapshot(
    db: Session,
    source_name: str,
    status: str,
    fetched: int = 0,
    saved: int = 0,
    completeness: float = 0.0,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
) -> DailyHealthSnapshot:
    """记录当天运行快照（幂等：同一天多次运行只创建一条或更新）。"""
    today = date_cls.today()

    existing = db.query(DailyHealthSnapshot).filter(
        DailyHealthSnapshot.source_name == source_name,
        DailyHealthSnapshot.snapshot_date == today,
    ).first()

    if existing:
        # 更新当天已有的快照：保留最佳状态
        existing.runs = (existing.runs or 0) + 1
        existing.fetched = (existing.fetched or 0) + fetched
        existing.saved = (existing.saved or 0) + saved
        if status == "success":
            existing.status = "success"
        elif existing.status == "success" and status in ("partial", "failed"):
            existing.status = "partial"
        if completeness > 0:
            existing.completeness = completeness
        if error_type:
            existing.error_type = error_type
        if error_message:
            existing.error_message = error_message
        db.flush()
        return existing

    snapshot = DailyHealthSnapshot(
        source_name=source_name,
        snapshot_date=today,
        status=status,
        runs=1,
        fetched=fetched,
        saved=saved,
        completeness=completeness,
        error_type=error_type,
        error_message=error_message,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _recompute_continuous_from_snapshots(
    db: Session,
    health: CrawlSourceHealth,
) -> None:
    """从 daily_health_snapshots 重新计算连续天数和观测天数。

    这是唯一计算 observed_days / consecutive_success_days 的函数。
    不得通过 first_run_at / last_run_at 推断连续运行。
    """
    today = date_cls.today()

    snapshots = (
        db.query(DailyHealthSnapshot)
        .filter(DailyHealthSnapshot.source_name == health.source_name)
        .order_by(DailyHealthSnapshot.snapshot_date.desc())
        .all()
    )

    if not snapshots:
        health.observed_days = 0
        health.consecutive_success_days = 0
        return

    # observed_days: 有多少个自然日有运行记录
    health.observed_days = len(set(s.snapshot_date for s in snapshots))

    # consecutive_success_days: 从今天往前数，连续每天 success 的天数
    consecutive = 0
    check_date = today
    # 如果今天没有运行记录，从昨天开始算
    today_snapshot = next(
        (s for s in snapshots if s.snapshot_date == today), None
    )
    if not today_snapshot:
        check_date = today - timedelta(days=1)

    for _ in range(365):  # 最多回溯 365 天
        day_snapshot = next(
            (s for s in snapshots if s.snapshot_date == check_date), None
        )
        if day_snapshot is None:
            # 这天没有记录 → gap，停止计数
            break
        if day_snapshot.status == "success":
            consecutive += 1
            check_date = check_date - timedelta(days=1)
        else:
            # 这天有运行但不是 success → 停止计数
            break

    health.consecutive_success_days = consecutive


# ── 更新服务 ──────────────────────────────────────────────────


def update_source_health(
    db: Session,
    source_name: str,
    *,
    status: str,
    fetched: int = 0,
    saved: int = 0,
    duplicates: int = 0,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    completeness: float = 0.0,
) -> CrawlSourceHealth:
    """每次来源采集完成后调用，更新持久化健康记录。

    幂等、无副作用、返回更新后的记录。
    """
    now = datetime.now(timezone.utc)

    health = db.query(CrawlSourceHealth).filter(
        CrawlSourceHealth.source_name == source_name
    ).first()

    if health is None:
        health = CrawlSourceHealth(source_name=source_name)
        db.add(health)

    # 更新运行时间线
    if health.first_run_at is None:
        health.first_run_at = now
    health.last_run_at = now
    health.total_runs = (health.total_runs or 0) + 1

    # 更新最近运行状态
    health.last_status = status

    # 累计产出统计
    health.fetched_count = (health.fetched_count or 0) + fetched
    health.saved_count = (health.saved_count or 0) + saved
    health.duplicate_count = (health.duplicate_count or 0) + duplicates

    if status == "success":
        health.last_success_at = now
        health.last_success_date = now.date()
        health.successful_runs = (health.successful_runs or 0) + 1
        health.consecutive_failures = 0
        # 成功后清空错误信息
        health.last_error_type = None
        health.last_error_message = None
    elif status == "partial":
        # partial 也视为有产出，但增加失败计数
        health.consecutive_failures = (health.consecutive_failures or 0) + 1
    elif status == "failed":
        health.consecutive_failures = (health.consecutive_failures or 0) + 1

    # 更新错误信息（写作前统一脱敏）
    if error_type:
        health.last_error_type = _sanitize_error_type(error_type)
    if error_message:
        health.last_error_message = _sanitize_error_message(error_message)

    # 更新完整率（Weighted Moving Average）
    if health.total_runs > 0 and completeness > 0:
        prev = health.completeness_rate or 0.0
        health.completeness_rate = round(prev * (1 - WMA_ALPHA) + completeness * WMA_ALPHA, 4)

    # ── 记录每日快照（在计算连续天数前）─────────────
    _record_daily_snapshot(
        db, source_name, status=status,
        fetched=fetched, saved=saved,
        completeness=completeness,
        error_type=_sanitize_error_type(error_type) if error_type else None,
        error_message=_sanitize_error_message(error_message) if error_message else None,
    )

    # ── 从快照重新计算连续天数 ─────────────────────
    _recompute_continuous_from_snapshots(db, health)

    # 计算并更新健康状态
    health.health_status = compute_health_status(health, now=now)
    health.updated_at = now

    db.flush()
    return health


def get_all_source_health(db: Session) -> list[CrawlSourceHealth]:
    """获取所有来源的健康记录（按 source_name 排序）。"""
    return (
        db.query(CrawlSourceHealth)
        .order_by(CrawlSourceHealth.source_name)
        .all()
    )


def get_source_health(db: Session, source_name: str) -> Optional[CrawlSourceHealth]:
    """获取单个来源的健康记录。"""
    return db.query(CrawlSourceHealth).filter(
        CrawlSourceHealth.source_name == source_name
    ).first()


def ensure_all_sources_exist(db: Session) -> None:
    """确保所有 4 个来源在 crawl_source_health 中有占位记录。

    首次创建时 health_status = collecting。
    """
    for src in _ALL_SOURCES:
        existing = db.query(CrawlSourceHealth).filter(
            CrawlSourceHealth.source_name == src
        ).first()
        if existing is None:
            db.add(CrawlSourceHealth(
                source_name=src,
                health_status="collecting",
            ))
    db.flush()
