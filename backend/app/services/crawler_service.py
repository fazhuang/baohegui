"""政府采购投诉案例爬虫服务

数据源:
1. ccgp.gov.cn/jdjc/jdcf/ — 全国综合（3页，约60条）
2. ccgp-ningxia.gov.cn — 宁夏区本级投诉处理（23条）
3. 财政部信息公告 gks.mof.gov.cn（扩展中）
"""

from __future__ import annotations

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


async def _fetch_text(url: str, client: httpx.AsyncClient) -> str:
    """抓取URL内容（带重试）"""
    for attempt in range(3):
        try:
            resp = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.warning("CCGP 403 Forbidden（需要 Cloudflare 绕过）: %s", url)
                return ""
            if attempt < 2:
                await asyncio.sleep(1)
            else:
                logger.warning("抓取失败 %s: %s", url, e)
                return ""
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(1)
            else:
                logger.warning("抓取失败 %s: %s", url, e)
                return ""
    return ""


async def crawl_ccgp_list(client: httpx.AsyncClient) -> list[dict]:
    """爬取 ccgp.gov.cn 监督处罚列表页"""
    items: list[dict] = []
    seen_hrefs: set = set()
    for page_url in CCGP_JDJC_PAGES:
        html = await _fetch_text(page_url, client)
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


async def crawl_ccgp_detail(url: str, client: httpx.AsyncClient) -> Optional[dict]:
    """爬取单条投诉详情并结构化提取"""
    html = await _fetch_text(url, client)
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
        "complaint_types": str(complaint_kw) if complaint_kw else "",
        "legal_basis": "",
        "summary": (result_section or "")[:500],
        "raw_content": raw_text[:5000],
        "is_analyzed": 0,
    }


# ── 宁夏爬虫 ──────────────────────────────────────────────────


async def crawl_ningxia_list(client: httpx.AsyncClient) -> list[dict]:
    """爬取宁夏投诉处理列表页"""
    items: list[dict] = []
    seen_urls: set = set()
    for page_url in NINGXIA_TS_PAGES:
        html = await _fetch_text(page_url, client)
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
    """执行全部可爬取数据源的采集"""
    stats = {"ccgp": 0, "ningxia": 0, "shaanxi": 0, "mof": 0, "errors": [], "cases_saved": 0}

    async with httpx.AsyncClient(verify=False) as client:
        # ── CCGP 全国 ──
        try:
            ccgp_items = await crawl_ccgp_list(client)
            logger.info("CCGP 列表: %d 条", len(ccgp_items))
            saved = 0
            for item in ccgp_items:
                d = await crawl_ccgp_detail(item["url"], client)
                if d and _save_case(d):
                    saved += 1
                await asyncio.sleep(0.3)
            stats["ccgp"] = saved
        except Exception as e:
            logger.error("CCGP 异常: %s", e)
            stats["errors"].append(f"ccgp: {e}")

        # ── 宁夏 ──
        try:
            nx_items = await crawl_ningxia_list(client)
            logger.info("宁夏列表: %d 条", len(nx_items))
            saved = 0
            for item in nx_items:
                d = await crawl_ccgp_detail(item["url"], client)
                if d:
                    d["province"] = "宁夏"
                    if _save_case(d):
                        saved += 1
                await asyncio.sleep(0.3)
            stats["ningxia"] = saved
        except Exception as e:
            logger.error("宁夏异常: %s", e)
            stats["errors"].append(f"ningxia: {e}")

    # ── 陕西（Playwright，单独处理） ──
    try:
        from app.services.browser_crawler import crawl_shaanxi
        stats["shaanxi"] = await crawl_shaanxi()
    except Exception as e:
        logger.error("陕西异常: %s", e)
        stats["errors"].append(f"shaanxi: {e}")

    stats["cases_saved"] = stats["ccgp"] + stats["ningxia"] + stats["shaanxi"] + stats["mof"]

    # ── 财政部信息公告（独立处理） ──
    try:
        from app.services.mof_crawler import fetch_gks_list

        mof_items = await fetch_gks_list(client)
        logger.info("财政部列表: %d 条", len(mof_items))
        saved = 0
        for item in mof_items[:20]:  # 限20条
            d = await crawl_ccgp_detail(item["url"], client)
            if d:
                d["province"] = "全国"
                if _save_case(d):
                    saved += 1
            await asyncio.sleep(0.3)
        stats["mof"] = saved
    except Exception as e:
        logger.error("财政部异常: %s", e)
        stats["errors"].append(f"mof: {e}")

    return stats


# ── 持久化 ─────────────────────────────────────────────────────


def _save_case(data: dict) -> bool:
    """将一条案例写入数据库（去重）"""
    db: Session = SessionLocal()
    try:
        existing = db.query(ComplaintCase).filter(
            ComplaintCase.source_url == data["source_url"]
        ).first()
        if existing:
            return False
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
    q = db.query(ComplaintCase)
    if province:
        q = q.filter(ComplaintCase.province == province)
    if decision_type:
        q = q.filter(ComplaintCase.decision_type == decision_type)
    return q.order_by(ComplaintCase.created_at.desc()).offset(offset).limit(limit).all()


def count_cases(db: Session) -> dict:
    """统计各类型案例数量"""
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
