"""政府采购投诉案例爬虫服务

数据源:
1. ccgp.gov.cn/jdjc/jdcf/ — 全国综合（3页，约60条）
2. ccgp-ningxia.gov.cn — 宁夏区本级投诉处理（23条）
3. 财政部信息公告 gks.mof.gov.cn（扩展中）

解析职责委托至 app.services.parse_contract（纯函数，无网络 I/O）。
网络 I/O 留在本模块。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.complaint_case import ComplaintCase
from app.services.parse_contract import (
    CCGP_BASE,
    DECISION_TYPE_MAP,
    NINGXIA_BASE,
    SOURCE_META,
    _compute_completeness,
    extract_decision_type,
    extract_field,
    parse_ccgp_list_html,
    parse_detail_html,
    parse_ningxia_list_html,
)

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────

CCGP_JDJC_PAGES = [
    f"{CCGP_BASE}/jdjc/jdcf/index.htm",
    f"{CCGP_BASE}/jdjc/jdcf/index_1.htm",
]

NINGXIA_TS_PAGES = [
    f"{NINGXIA_BASE}/public/NXGPPNEW/dynamic/contents/TSCL/index.jsp?cid=2065&sid=1&tab=Q",
    f"{NINGXIA_BASE}/public/NXGPPNEW/dynamic/contents/TSCL/index.jsp?cid=2065&sid=1&pageNo=2&tab=Q",
    f"{NINGXIA_BASE}/public/NXGPPNEW/dynamic/contents/TSCL/index.jsp?cid=2065&sid=1&tab=S",
]

SHAANXI_BASE = "https://www.ccgp-shaanxi.gov.cn"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── 重新导出纯解析函数，保持向后兼容 ──────────────────────────

_extract_decision_type = extract_decision_type
_extract_field = extract_field
_compute_completeness = _compute_completeness  # re-export for browser_crawler / mof_crawler
DECISION_TYPE_MAP = DECISION_TYPE_MAP  # noqa: F811 (re-export)

# ── CCGP 列表爬虫（网络 I/O 包装纯函数） ─────────────────────


async def _fetch_text(url: str, fetcher) -> str:
    """使用 SafeFetcher 抓取 URL 内容。

    fetcher 必须是 SafeFetcher 实例（已配置域名白名单 + TLS）。
    一旦失败抛出异常，由上游捕获并记录，不得静默返回空字符串。
    """
    from app.services.safe_fetcher import SafeFetchError, SafeFetcher

    for attempt in range(3):
        try:
            return await fetcher.get(url)
        except SafeFetchError as e:
            if e.error_type.value == "http_error" and e.status_code == 403:
                logger.warning("403 Forbidden: %s", url)
                raise
            if attempt < 2:
                await asyncio.sleep(1)
            else:
                raise
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(1)
            else:
                raise
    raise SafeFetchError(
        error_type="network",
        message=f"重试耗尽: {url}",
        url=url,
        source=str(getattr(fetcher, '_source', '')),
    )


async def crawl_ccgp_list(fetcher) -> list[dict]:
    """爬取 ccgp.gov.cn 监督处罚列表页（网络 I/O + 纯解析）"""
    items: list[dict] = []
    seen_hrefs: set = set()
    for page_url in CCGP_JDJC_PAGES:
        html = await _fetch_text(page_url, fetcher)
        if not html:
            continue
        page_items = parse_ccgp_list_html(html)
        for item in page_items:
            if item["url"] in seen_hrefs:
                continue
            seen_hrefs.add(item["url"])
            items.append(item)
    return items


async def crawl_ccgp_detail(url: str, fetcher) -> Optional[dict]:
    """爬取单条投诉详情并结构化提取（网络 I/O + 纯解析）"""
    html = await _fetch_text(url, fetcher)
    if not html:
        return None
    return parse_detail_html(html, url=url, province="全国")


# ── 宁夏爬虫 ──────────────────────────────────────────────────


async def crawl_ningxia_list(fetcher) -> list[dict]:
    """爬取宁夏投诉处理列表页（网络 I/O + 纯解析）"""
    items: list[dict] = []
    seen_urls: set = set()
    for page_url in NINGXIA_TS_PAGES:
        html = await _fetch_text(page_url, fetcher)
        if not html:
            continue
        page_items = parse_ningxia_list_html(html)
        for item in page_items:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            items.append(item)
    return items


# ── 来源状态判定 ──────────────────────────────────────────────

def _source_status(fetched: int, parsed_count: int, saved: int, errors: list) -> str:
    """根据抓取、解析、保存产出判定来源最终状态。

    规则（按优先级）：
    - fetched == 0 → "success"（暂无新内容，非失败）
    - fetched > 0 且 parsed_count == 0 → "failed"（全部解析失败，含 errors）
    - 有 errors 但仍有产出（saved > 0 或 parsed_count > 0）→ "partial"
    - fetched > 0 且 saved == 0 但 parsed_count > 0 → "partial"（解析成功但全部重复）
    - 否则 → "success"
    """
    if fetched == 0:
        return "success"
    if fetched > 0 and parsed_count == 0:
        # 全部解析失败 → 总是 failed，有无 errors 均同
        return "failed"
    if errors:
        # 部分条目失败但仍有有效产出 → partial
        return "partial"
    if fetched > 0 and saved == 0 and parsed_count > 0:
        # 解析成功但全部重复 → partial
        return "partial"
    return "success"


# ── 统一入口 ──────────────────────────────────────────────────

# 所有采集来源
_ALL_SOURCES = ("ccgp", "ningxia", "shaanxi", "mof")


def _new_source_stats() -> dict:
    """创建统一的来源统计结构。

    Returns dict with keys: saved, fetched, duplicates, errors, status,
    error_type, error_message, completeness_rate, parsed_count,
    completeness_sum, parse_failed_count。总是同一结构。
    """
    return {
        "saved": 0, "fetched": 0, "duplicates": 0,
        "errors": [], "status": "success",
        "error_type": None, "error_message": None,
        "completeness_rate": None,  # 字段完整率 (0.0–1.0), None=无解析结果
        "parsed_count": 0,           # 成功解析的条目数
        "completeness_sum": 0.0,     # 所有解析条目的完整度之和
        "parse_failed_count": 0,     # 解析失败的条目数
    }


async def crawl_all() -> dict:
    """执行全部可爬取数据源的采集。

    每个来源使用独立的 SafeFetcher（自带域名白名单 + DNS 校验）。
    来源失败时，记录具体错误但继续采集其他来源。

    每个来源始终有统一统计结构：saved, fetched, duplicates, errors,
    status, error_type, error_message。
    """
    from app.services.safe_fetcher import SafeFetchError, fetcher_for_source

    stats = {
        "ccgp": _new_source_stats(),
        "ningxia": _new_source_stats(),
        "shaanxi": _new_source_stats(),
        "mof": _new_source_stats(),
        "kg_synced": 0,
        "errors": [],
        "cases_saved": 0,
    }

    # ── CCGP 全国 ──────────────────────────────────────
    try:
        async with fetcher_for_source("ccgp") as fetcher:
            ccgp_items = await crawl_ccgp_list(fetcher)
            logger.info("CCGP 列表: %d 条", len(ccgp_items))
            saved = 0
            parsed_count = 0
            completeness_sum = 0.0
            parse_failed = 0
            for item in ccgp_items:
                try:
                    d = await crawl_ccgp_detail(item["url"], fetcher)
                    if d:
                        parsed_count += 1
                        # 计算每条案例的字段完整度
                        item_completeness = _compute_completeness(d, "ccgp")
                        completeness_sum += item_completeness
                        if _save_case(d):
                            saved += 1
                    else:
                        # 详情页返回 None（HTML 为空或解析完全失败）
                        parse_failed += 1
                except SafeFetchError as e:
                    stats["ccgp"]["errors"].append(f"{item['url']}: {e.error_type.value}={e.message}")
                    parse_failed += 1
                await asyncio.sleep(0.3)
            stats["ccgp"]["saved"] = saved
            stats["ccgp"]["fetched"] = len(ccgp_items)
            stats["ccgp"]["parsed_count"] = parsed_count
            stats["ccgp"]["completeness_sum"] = completeness_sum
            stats["ccgp"]["completeness_rate"] = (
                round(completeness_sum / parsed_count, 4) if parsed_count > 0 else None
            )
            stats["ccgp"]["parse_failed_count"] = parse_failed
            stats["ccgp"]["status"] = _source_status(
                stats["ccgp"]["fetched"], stats["ccgp"]["parsed_count"],
                stats["ccgp"]["saved"], stats["ccgp"]["errors"])
            if stats["ccgp"]["errors"]:
                stats["ccgp"]["error_type"] = "item_errors"
                stats["ccgp"]["error_message"] = _summarize_errors(stats["ccgp"]["errors"])
            elif stats["ccgp"]["status"] == "failed" and stats["ccgp"]["fetched"] > 0:
                stats["ccgp"]["error_type"] = "parse_all_failed"
                stats["ccgp"]["error_message"] = f"全部 {stats['ccgp']['fetched']} 条详情解析失败"
    except SafeFetchError as e:
        logger.error("CCGP 安全抓取错误: %s", e)
        stats["ccgp"]["errors"].append(f"{e.error_type.value}: {e.message}")
        stats["ccgp"]["error_type"] = e.error_type.value
        stats["ccgp"]["error_message"] = _safe_error_summary(str(e))
        stats["ccgp"]["status"] = "failed"
    except Exception as e:
        safe_e = _safe_error_summary(str(e))
        logger.error("CCGP 异常: %s", safe_e)
        stats["ccgp"]["errors"].append(f"exception: {safe_e}")
        stats["ccgp"]["error_type"] = "exception"
        stats["ccgp"]["error_message"] = safe_e
        stats["ccgp"]["status"] = "failed"

    # ── 宁夏 ────────────────────────────────────────────
    try:
        async with fetcher_for_source("ningxia") as fetcher:
            nx_items = await crawl_ningxia_list(fetcher)
            logger.info("宁夏列表: %d 条", len(nx_items))
            saved = 0
            parsed_count = 0
            completeness_sum = 0.0
            parse_failed = 0
            for item in nx_items:
                try:
                    d = await crawl_ccgp_detail(item["url"], fetcher)
                    if d:
                        d["province"] = "宁夏"
                        parsed_count += 1
                        item_completeness = _compute_completeness(d, "ningxia")
                        completeness_sum += item_completeness
                        if _save_case(d):
                            saved += 1
                    else:
                        parse_failed += 1
                except SafeFetchError as e:
                    stats["ningxia"]["errors"].append(f"{item['url']}: {e.error_type.value}={e.message}")
                    parse_failed += 1
                await asyncio.sleep(0.3)
            stats["ningxia"]["saved"] = saved
            stats["ningxia"]["fetched"] = len(nx_items)
            stats["ningxia"]["parsed_count"] = parsed_count
            stats["ningxia"]["completeness_sum"] = completeness_sum
            stats["ningxia"]["completeness_rate"] = (
                round(completeness_sum / parsed_count, 4) if parsed_count > 0 else None
            )
            stats["ningxia"]["parse_failed_count"] = parse_failed
            stats["ningxia"]["status"] = _source_status(
                stats["ningxia"]["fetched"], stats["ningxia"]["parsed_count"],
                stats["ningxia"]["saved"], stats["ningxia"]["errors"])
            if stats["ningxia"]["errors"]:
                stats["ningxia"]["error_type"] = "item_errors"
                stats["ningxia"]["error_message"] = _summarize_errors(stats["ningxia"]["errors"])
            elif stats["ningxia"]["status"] == "failed" and stats["ningxia"]["fetched"] > 0:
                stats["ningxia"]["error_type"] = "parse_all_failed"
                stats["ningxia"]["error_message"] = f"全部 {stats['ningxia']['fetched']} 条详情解析失败"
    except SafeFetchError as e:
        stats["ningxia"]["errors"].append(f"{e.error_type.value}: {e.message}")
        stats["ningxia"]["error_type"] = e.error_type.value
        stats["ningxia"]["error_message"] = _safe_error_summary(str(e))
        stats["ningxia"]["status"] = "failed"
    except Exception as e:
        safe_e = _safe_error_summary(str(e))
        logger.error("宁夏 异常: %s", safe_e)
        stats["ningxia"]["errors"].append(f"exception: {safe_e}")
        stats["ningxia"]["error_type"] = "exception"
        stats["ningxia"]["error_message"] = safe_e
        stats["ningxia"]["status"] = "failed"

    # ── 陕西（Playwright，独立 client） ──────────────────
    try:
        from app.services.browser_crawler import crawl_shaanxi
        shaanxi_result = await crawl_shaanxi()
        if isinstance(shaanxi_result, dict):
            stats["shaanxi"]["saved"] = shaanxi_result.get("saved", 0)
            stats["shaanxi"]["parsed_count"] = shaanxi_result.get("parsed_count", 0)
            stats["shaanxi"]["completeness_sum"] = shaanxi_result.get("completeness_sum", 0.0)
            stats["shaanxi"]["completeness_rate"] = (
                round(stats["shaanxi"]["completeness_sum"] / stats["shaanxi"]["parsed_count"], 4)
                if stats["shaanxi"]["parsed_count"] > 0 else None
            )
            # fetched = 列表页条目数（非已解析数），用于 _source_status 判定
            stats["shaanxi"]["fetched"] = shaanxi_result.get("listed", 0)
            stats["shaanxi"]["parse_failed_count"] = shaanxi_result.get("parse_failed", 0)
            # fetched>0 且 saved==parsed_count==0 → 全部解析失败，必须 failed
            stats["shaanxi"]["status"] = _source_status(
                stats["shaanxi"]["fetched"], stats["shaanxi"]["parsed_count"],
                stats["shaanxi"]["saved"], stats["shaanxi"]["errors"])
            if stats["shaanxi"]["status"] == "failed" and stats["shaanxi"]["fetched"] > 0:
                stats["shaanxi"]["error_type"] = "parse_all_failed"
                stats["shaanxi"]["error_message"] = f"全部 {stats['shaanxi']['fetched']} 条详情解析失败"
        else:
            # 向后兼容：旧 int 返回值
            saved = shaanxi_result if isinstance(shaanxi_result, int) else 0
            stats["shaanxi"]["saved"] = saved
            stats["shaanxi"]["fetched"] = saved
            stats["shaanxi"]["status"] = "success" if saved > 0 else "failed"
    except Exception as e:
        safe_e = _safe_error_summary(str(e))
        logger.error("陕西 异常: %s", safe_e)
        stats["shaanxi"]["errors"].append(f"exception: {safe_e}")
        stats["shaanxi"]["error_type"] = "exception"
        stats["shaanxi"]["error_message"] = safe_e
        stats["shaanxi"]["status"] = "failed"

    # ── 财政部信息公告（独立处理） ───────────────────────
    try:
        from app.services.mof_crawler import fetch_gks_list

        async with fetcher_for_source("mof") as fetcher:
            mof_items = await fetch_gks_list(fetcher)
            logger.info("财政部列表: %d 条", len(mof_items))
            saved = 0
            parsed_count = 0
            completeness_sum = 0.0
            parse_failed = 0
            for item in mof_items[:20]:
                try:
                    d = await crawl_ccgp_detail(item["url"], fetcher)
                    if d:
                        d["province"] = "全国"
                        parsed_count += 1
                        item_completeness = _compute_completeness(d, "mof")
                        completeness_sum += item_completeness
                        if _save_case(d):
                            saved += 1
                    else:
                        parse_failed += 1
                except SafeFetchError as e:
                    stats["mof"]["errors"].append(f"{item['url']}: {e.error_type.value}={e.message}")
                    parse_failed += 1
                await asyncio.sleep(0.3)
            stats["mof"]["saved"] = saved
            stats["mof"]["fetched"] = len(mof_items)
            stats["mof"]["parsed_count"] = parsed_count
            stats["mof"]["completeness_sum"] = completeness_sum
            stats["mof"]["completeness_rate"] = (
                round(completeness_sum / parsed_count, 4) if parsed_count > 0 else None
            )
            stats["mof"]["parse_failed_count"] = parse_failed
            stats["mof"]["status"] = _source_status(
                stats["mof"]["fetched"], stats["mof"]["parsed_count"],
                stats["mof"]["saved"], stats["mof"]["errors"])
            if stats["mof"]["errors"]:
                stats["mof"]["error_type"] = "item_errors"
                stats["mof"]["error_message"] = _summarize_errors(stats["mof"]["errors"])
            elif stats["mof"]["status"] == "failed" and stats["mof"]["fetched"] > 0:
                stats["mof"]["error_type"] = "parse_all_failed"
                stats["mof"]["error_message"] = f"全部 {stats['mof']['fetched']} 条详情解析失败"
    except SafeFetchError as e:
        logger.error("财政部 安全抓取错误: %s", e)
        stats["mof"]["errors"].append(f"{e.error_type.value}: {e.message}")
        stats["mof"]["error_type"] = e.error_type.value
        stats["mof"]["error_message"] = _safe_error_summary(str(e))
        stats["mof"]["status"] = "failed"
    except Exception as e:
        safe_e = _safe_error_summary(str(e))
        logger.error("财政部 异常: %s", safe_e)
        stats["mof"]["errors"].append(f"exception: {safe_e}")
        stats["mof"]["error_type"] = "exception"
        stats["mof"]["error_message"] = safe_e
        stats["mof"]["status"] = "failed"

    # ── 汇总 ───────────────────────────────────────────
    stats["cases_saved"] = (
        stats["ccgp"]["saved"] +
        stats["ningxia"]["saved"] +
        stats["shaanxi"]["saved"] +
        stats["mof"]["saved"]
    )
    # 展平 errors 用于兼容旧 consumer
    for src_key in _ALL_SOURCES:
        for err in stats[src_key]["errors"]:
            stats["errors"].append(f"{src_key}: {err}")

    # ── 同步到 KG（仅 published 案例） ──────────────────
    try:
        from app.services.kg_projection import kg_projection

        db = SessionLocal()
        try:
            kg_result = kg_projection.project_all_published(db, limit=500)
            stats["kg_synced"] = kg_result["created"] + kg_result["updated"]
            db.commit()
        finally:
            db.close()
    except Exception as e:
        safe_msg = _safe_error_summary(str(e))
        logger.error("案例同步 KG 失败: %s", safe_msg)
        stats["errors"].append(f"kg_sync: {safe_msg}")

    return stats


# ── 持久化 ─────────────────────────────────────────────────────


def _save_case(data: dict) -> bool:
    """将一条案例写入数据库（去重）

    自动转换 decision_date 字符串为 date 对象。
    """
    db: Session = SessionLocal()
    try:
        existing = db.query(ComplaintCase).filter(
            ComplaintCase.source_url == data["source_url"]
        ).first()
        if existing:
            return False

        # 兼容字符串日期 → Date 类型
        if "decision_date" in data and isinstance(data["decision_date"], str):
            from datetime import date as date_cls
            raw_d = data["decision_date"].strip()
            if raw_d:
                try:
                    data["decision_date"] = date_cls.fromisoformat(raw_d)
                except (ValueError, TypeError):
                    data["decision_date"] = None
            else:
                data["decision_date"] = None

        case = ComplaintCase(**data)
        db.add(case)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.warning("保存案例失败: %s", e)
        return False
    finally:
        db.close()


# ── 错误摘要工具 ───────────────────────────────────────────────

_MAX_ERROR_CHARS = 2000

# 敏感的凭证/Token 模式 — 必须全部脱敏
_CREDENTIAL_PATTERNS = [
    # Authorization: Bearer TOKEN  /  Authorization=Bearer TOKEN
    (r'(?:Authorization|Auth)\s*[=:]\s*Bearer\s+\S+', '[REDACTED]', True),
    # Authorization: Basic BASE64
    (r'(?:Authorization|Auth)\s*[=:]\s*Basic\s+\S+', '[REDACTED]', True),
    # Bearer TOKEN (standalone — Authorization: Bearer cases already handled above)
    (r'\bBearer\s+[\w\-\.\+/]+', 'Bearer [REDACTED]', True),
    # Token: VALUE / Token=VALUE
    (r'\b(?:Token|access_token|refresh_token)\s*[=:]\s*\S+', '[REDACTED]', True),
    # api_key=VALUE / api-key: VALUE
    (r'\bapi[_-]?key\s*[=:]\s*\S+', '[REDACTED]', True),
    # client_secret=VALUE (OAuth)
    (r'\bclient[_-]?secret\s*[=:]\s*\S+', '[REDACTED]', True),
    # secret=VALUE (standalone)
    (r'\bsecret\s*[=:]\s*\S+', '[REDACTED]', True),
    # password=VALUE (常用于参数或 URL)
    (r'\bpassword\s*[=:]\s*\S+', '[REDACTED]', True),
    # Cookie: ... / Set-Cookie: ... (整行脱敏)
    (r'(?:Cookie|Set-Cookie)\s*[=:]\s*.+?(?:\r?\n|$)', '[REDACTED]', True),
    # URL query 中的 token/key/password/secret/signature/client_secret= VALUE
    (r'(?:[?&])(token|key|password|secret|signature|sig|client_secret)=[^&\s]+', '?\\1=[REDACTED]', True),
]
_CREDENTIAL_REPLACEMENT = '[REDACTED]'


def _safe_error_summary(message: str) -> str:
    """截断错误字符串，移除可能的凭据/Token。

    规则：
    - 长度上限 _MAX_ERROR_CHARS
    - 过滤所有 _CREDENTIAL_PATTERNS 中定义的敏感模式
    - 整个敏感值替换为 [REDACTED]，不保留片段
    - 忽略大小写
    """
    import re as _re
    cleaned = str(message)
    for pattern, replacement, ignore_case in _CREDENTIAL_PATTERNS:
        flags = _re.IGNORECASE if ignore_case else 0
        cleaned = _re.sub(pattern, replacement, cleaned, flags=flags)
    if len(cleaned) > _MAX_ERROR_CHARS:
        cleaned = cleaned[:_MAX_ERROR_CHARS] + "..."
    return cleaned


def _summarize_errors(errors: list[str], max_len: int = 3) -> str:
    """从错误列表生成有限摘要。

    仅包含前 max_len 条，每条截断长度。
    """
    selected = errors[:max_len]
    summaries = []
    for err in selected:
        s = _safe_error_summary(str(err))
        if len(s) > 300:
            s = s[:300]
        summaries.append(s)
    if len(errors) > max_len:
        summaries.append(f"...and {len(errors) - max_len} more errors")
    return "; ".join(summaries)


def query_cases(
    db: Session,
    province: str = "",
    decision_type: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[ComplaintCase]:
    """查询已采集案例"""
    q = _build_case_query(db, province=province, decision_type=decision_type)
    return q.order_by(ComplaintCase.created_at.desc()).offset(offset).limit(limit).all()


def count_cases(db: Session, province: str = "", decision_type: str = "") -> int:
    """返回符合筛选条件的案例总数"""
    q = _build_case_query(db, province=province, decision_type=decision_type)
    return q.count()


def _build_case_query(db: Session, province: str = "", decision_type: str = ""):
    """构建带筛选条件的案例查询"""
    q = db.query(ComplaintCase)
    if province:
        q = q.filter(ComplaintCase.province == province)
    if decision_type:
        q = q.filter(ComplaintCase.decision_type == decision_type)
    return q


def count_case_stats(db: Session) -> dict:
    """统计各类型案例数量（用于 /api/crawler/stats）"""
    total = db.query(ComplaintCase).count()
    upheld = db.query(ComplaintCase).filter(ComplaintCase.decision_type == "upheld").count()
    rejected = db.query(ComplaintCase).filter(ComplaintCase.decision_type == "rejected").count()
    partial = db.query(ComplaintCase).filter(ComplaintCase.decision_type == "partial").count()
    return {
        "total": total,
        "upheld": upheld,
        "rejected": rejected,
        "partial": partial,
        "dismissed": total - upheld - rejected - partial,
    }
