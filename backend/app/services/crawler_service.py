"""政府采购投诉案例爬虫服务

数据源:
1. ccgp.gov.cn/jdjc/jdcf/ — 全国综合（3页，约60条）
2. ccgp-ningxia.gov.cn — 宁夏区本级投诉处理（23条）
3. 财政部信息公告 gks.mof.gov.cn（扩展中）
"""

from __future__ import annotations

import json
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.complaint_case import ComplaintCase

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────

CCGP_BASE = "https://www.ccgp.gov.cn"
CCGP_JDJC_PAGES = [
    f"{CCGP_BASE}/jdjc/jdcf/index.htm",
    f"{CCGP_BASE}/jdjc/jdcf/index_1.htm",
]

NINGXIA_BASE = "https://www.ccgp-ningxia.gov.cn"
NINGXIA_TS_PAGES = [
    f"{NINGXIA_BASE}/public/NXGPPNEW/dynamic/contents/TSCL/index.jsp?cid=2065&sid=1&tab=Q",
    f"{NINGXIA_BASE}/public/NXGPPNEW/dynamic/contents/TSCL/index.jsp?cid=2065&sid=1&pageNo=2&tab=Q",  # 第2页区本级
    f"{NINGXIA_BASE}/public/NXGPPNEW/dynamic/contents/TSCL/index.jsp?cid=2065&sid=1&tab=S",  # 市县
]

SHAANXI_BASE = "https://www.ccgp-shaanxi.gov.cn"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DECISION_TYPE_MAP = {
    "驳回投诉": "rejected",
    "驳回": "rejected",
    "投诉不成立": "rejected",
    "投诉成立": "upheld",
    "责令重新": "upheld",
    "中标无效": "upheld",
    "部分成立": "partial",
    "部分": "partial",
    "撤销合同": "upheld",
    "废标": "upheld",
    "重新开展": "upheld",
}

# ── 工具函数 ──────────────────────────────────────────────────


def _extract_decision_type(text: str) -> str:
    """从处理结果中提取决定类型"""
    for keyword, dtype in DECISION_TYPE_MAP.items():
        if keyword in text:
            return dtype
    return "dismissed"


def _extract_field(text: str, label: str, max_chars: int = 500) -> str:
    """从文本中提取指定标签后的内容"""
    # 优先使用序号标题作为结束标记
    next_section = r"(?:[一二三四五六七八九十]、|基本情况|处理依据及结果|处理依据|处理决定|其他补充)"
    patterns = [
        rf"{label}[：:]\s*(.+?)(?:\n(?:[一二三四五六七八九十]、|$))",
        rf"{label}[：:]\s*(.+?)(?:{next_section})",
        rf"{label}[：:]\s*(.+?)(?:\n\n)",
        rf"{label}[：:]\s*(.+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            val = m.group(1).strip()
            if len(val) > max_chars:
                val = val[:max_chars] + "..."
            return val
    return ""


# ── CCGP 爬虫 ────────────────────────────────────────────────


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
    """爬取 ccgp.gov.cn 监督处罚列表页"""
    items: list[dict] = []
    seen_hrefs: set = set()
    for page_url in CCGP_JDJC_PAGES:
        html = await _fetch_text(page_url, fetcher)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        # CCGP 列表：<li><a href="...">标题</a><span>日期</span></li>
        for ul in soup.find_all("ul"):
            for li in ul.find_all("li", recursive=False):
                a_tag = li.find("a")
                span = li.find("span")
                if not a_tag or not a_tag.get("href"):
                    continue
                href = a_tag["href"]
                if not href.startswith("./20"):
                    continue  # 只处理 ./2025/ ./2026/ 格式的链接
                title = a_tag.get_text(strip=True)
                if "投诉" not in title:
                    continue  # 只采集投诉处理公告
                full_href = CCGP_BASE + "/jdjc/jdcf" + href[1:]
                if full_href in seen_hrefs:
                    continue
                seen_hrefs.add(full_href)
                date_text = span.get_text(strip=True) if span else ""
                items.append({"title": title, "url": full_href, "date": date_text})
    return items


async def crawl_ccgp_detail(url: str, fetcher) -> Optional[dict]:
    """爬取单条投诉详情并结构化提取"""
    html = await _fetch_text(url, fetcher)
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")

    # 提取正文 — CCGP 页面 <ul class="list-content"> 中 <li> 是标题列表，
    # 详情页正文在 <div class="main-content"> 或直接 <body>
    raw_text = ""
    for sel in ["#main_contain", ".main-content", "article", ".article", ".content"]:
        div = soup.select_one(sel)
        if div:
            for aside in div.select(".sidebar, #sidebar, .aside, .right, .related, .nav, .navbar, .breadcrumb"):
                aside.decompose()
            raw_text = div.get_text("\n", strip=True)
            if len(raw_text.strip()) > 200:
                break
    # 宁夏 fallback: 取包含项目编号的 td
    if not raw_text or len(raw_text.strip()) < 100:
        for td in soup.find_all("td"):
            txt = td.get_text("\n", strip=True)
            if "项目编号" in txt or "项目名称" in txt:
                raw_text = txt
                break
    if not raw_text.strip():
        body = soup.find("body")
        raw_text = body.get_text("\n", strip=True) if body else ""
    # 确保文本长度
    if not raw_text.strip():
        raw_text = soup.find("body").get_text("\n", strip=True) if soup.find("body") else ""

    # 结构化字段提取
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    # 宁夏页面标题是"投诉处理"，用正文第一行含"公告"的句子
    if title in ("投诉处理", "") or "当前位置" in title:
        title_lines = raw_text.split("\n")
        for line in title_lines:
            if "政府采购投诉" in line or "投诉处理结果公告" in line:
                title = line.strip()[:200]
                break

    project_name = _extract_field(raw_text, "项目名称")
    project_number = _extract_field(raw_text, "项目编号")
    complainant = _extract_field(raw_text, "投诉人", 300)
    decision_date = ""
    for date_m in re.finditer(r"(\d{4})年(\d{1,2})月(\d{1,2})日", raw_text):
        candidate = f"{date_m.group(1)}-{date_m.group(2).zfill(2)}-{date_m.group(3).zfill(2)}"
        decision_date = candidate  # 取最后出现的日期（处理决定日期）

    # 提取处理依据及结果
    result_section = ""
    result_match = re.search(
        r"(?:五、处理依据及结果|五、处理依据|处理依据及结果|处理决定)(.*?)(?:六、|七、|$)",
        raw_text, re.DOTALL,
    )
    if result_match:
        result_section = result_match.group(1).strip()[:800]

    decision_type = _extract_decision_type(result_section or raw_text)

    # 提取投诉类型关键词
    complaint_kw = []
    for kw in [
        "参数", "品牌", "排他", "指向", "歧视", "授权", "检测报告", "资质",
        "中小企业", "虚假", "串通", "低价", "异常低价", "评分", "评审",
        "混包", "标准", "进口", "认证", "业绩", "售后",
    ]:
        if kw in raw_text:
            complaint_kw.append(kw)

    return {
        "province": "全国",
        "source_url": url,
        "title": title[:200],
        "project_name": (project_name or "")[:200],
        "project_number": (project_number or "")[:128],
        "complainant": (complainant or "")[:500],
        "respondent": "",
        "decision_date": decision_date,
        "decision_type": decision_type,
        "complaint_types": json.dumps(complaint_kw, ensure_ascii=False) if complaint_kw else "",
        "legal_basis": "",
        "summary": (result_section or "")[:500],
        "raw_content": raw_text[:5000],
        "is_analyzed": 0,
    }


# ── 宁夏爬虫 ──────────────────────────────────────────────────


async def crawl_ningxia_list(fetcher) -> list[dict]:
    """爬取宁夏投诉处理列表页"""
    items: list[dict] = []
    seen_urls: set = set()
    for page_url in NINGXIA_TS_PAGES:
        html = await _fetch_text(page_url, fetcher)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            title = a_tag.get_text(strip=True)
            if "投诉处理结果公告" not in title:
                continue
            if not href.startswith("contents/TSCL/"):
                continue
            full_url = f"{NINGXIA_BASE}/public/NXGPPNEW/dynamic/{href}"
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            items.append({"title": title, "url": full_url, "date": ""})
    return items


# ── 统一入口 ──────────────────────────────────────────────────


async def crawl_all() -> dict:
    """执行全部可爬取数据源的采集（Phase 2：来源级错误 + 统计）

    每个来源使用独立的 SafeFetcher（自带域名白名单 + DNS 校验）。
    来源失败时，记录具体错误但继续采集其他来源。

    Phase 2 增强：返回 per-source fetched/duplicates 统计，
    供 sync_scheduler 写入 crawl_job_items 持久化明细。
    """
    from app.services.safe_fetcher import SafeFetchError, fetcher_for_source

    stats = {
        "ccgp": {"saved": 0, "fetched": 0, "duplicates": 0, "errors": []},
        "ningxia": {"saved": 0, "fetched": 0, "duplicates": 0, "errors": []},
        "shaanxi": {"saved": 0, "fetched": 0, "duplicates": 0, "errors": []},
        "mof": {"saved": 0, "fetched": 0, "duplicates": 0, "errors": []},
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
            for item in ccgp_items:
                try:
                    d = await crawl_ccgp_detail(item["url"], fetcher)
                    if d and _save_case(d):
                        saved += 1
                except SafeFetchError as e:
                    stats["ccgp"]["errors"].append(f"{item['url']}: {e.error_type.value}={e.message}")
                await asyncio.sleep(0.3)
            stats["ccgp"]["saved"] = saved
            stats["ccgp"]["fetched"] = len(ccgp_items)
    except SafeFetchError as e:
        logger.error("CCGP 安全抓取错误: %s", e)
        stats["ccgp"]["errors"].append(f"{e.error_type.value}: {e.message}")
        stats["ccgp"]["error"] = str(e)
        stats["ccgp"]["error_type"] = e.error_type.value
    except Exception as e:
        logger.error("CCGP 异常: %s", e)
        stats["ccgp"]["errors"].append(f"exception: {e}")
        stats["ccgp"]["error"] = str(e)
        stats["ccgp"]["error_type"] = "exception"

    # ── 宁夏 ────────────────────────────────────────────
    try:
        async with fetcher_for_source("ningxia") as fetcher:
            nx_items = await crawl_ningxia_list(fetcher)
            logger.info("宁夏列表: %d 条", len(nx_items))
            saved = 0
            for item in nx_items:
                try:
                    d = await crawl_ccgp_detail(item["url"], fetcher)
                    if d:
                        d["province"] = "宁夏"
                        if _save_case(d):
                            saved += 1
                except SafeFetchError as e:
                    stats["ningxia"]["errors"].append(f"{item['url']}: {e.error_type.value}={e.message}")
                await asyncio.sleep(0.3)
            stats["ningxia"]["saved"] = saved
    except SafeFetchError as e:
        logger.error("宁夏 安全抓取错误: %s", e)
        stats["ningxia"]["errors"].append(f"{e.error_type.value}: {e.message}")
        stats["ningxia"]["error"] = str(e)
        stats["ningxia"]["error_type"] = e.error_type.value
    except Exception as e:
        logger.error("宁夏 异常: %s", e)
        stats["ningxia"]["errors"].append(f"exception: {e}")
        stats["ningxia"]["error"] = str(e)
        stats["ningxia"]["error_type"] = "exception"

    # ── 陕西（Playwright，独立 client） ──────────────────
    try:
        from app.services.browser_crawler import crawl_shaanxi
        stats["shaanxi"]["saved"] = await crawl_shaanxi()
    except Exception as e:
        logger.error("陕西 异常: %s", e)
        stats["shaanxi"]["errors"].append(f"exception: {e}")
        stats["shaanxi"]["error"] = str(e)
        stats["shaanxi"]["error_type"] = "exception"

    # ── 财政部信息公告（独立处理） ───────────────────────
    try:
        from app.services.mof_crawler import fetch_gks_list

        async with fetcher_for_source("mof") as fetcher:
            mof_items = await fetch_gks_list(fetcher)
            logger.info("财政部列表: %d 条", len(mof_items))
            saved = 0
            for item in mof_items[:20]:
                try:
                    d = await crawl_ccgp_detail(item["url"], fetcher)
                    if d:
                        d["province"] = "全国"
                        if _save_case(d):
                            saved += 1
                except SafeFetchError as e:
                    stats["mof"]["errors"].append(f"{item['url']}: {e.error_type.value}={e.message}")
                await asyncio.sleep(0.3)
            stats["mof"]["saved"] = saved
            stats["mof"]["fetched"] = len(mof_items)
    except SafeFetchError as e:
        logger.error("财政部 安全抓取错误: %s", e)
        stats["mof"]["errors"].append(f"{e.error_type.value}: {e.message}")
        stats["mof"]["error"] = str(e)
        stats["mof"]["error_type"] = e.error_type.value
    except Exception as e:
        logger.error("财政部 异常: %s", e)
        stats["mof"]["errors"].append(f"exception: {e}")
        stats["mof"]["error"] = str(e)
        stats["mof"]["error_type"] = "exception"

    # ── 汇总 ───────────────────────────────────────────
    stats["cases_saved"] = (
        stats["ccgp"]["saved"] +
        stats["ningxia"]["saved"] +
        stats["shaanxi"]["saved"] +
        stats["mof"]["saved"]
    )
    # 展平 errors 用于兼容旧 consumer
    for src_key in ("ccgp", "ningxia", "shaanxi", "mof"):
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
        logger.error("案例同步 KG 失败: %s", e)
        stats["errors"].append(f"kg_sync: {e}")

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
