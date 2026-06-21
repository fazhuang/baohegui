"""Playwright浏览器爬虫 — 处理陕西/青海/新疆等需要JS渲染的政府采购网"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from app.services.crawler_service import (
    _save_case,
    crawl_ccgp_detail,
    DECISION_TYPE_MAP,
)
from app.services.parse_contract import parse_shaanxi_list_html, _compute_completeness as pc

logger = logging.getLogger(__name__)

# ── 陕西 ──────────────────────────────────────────────────────

SHAANXI_TS_URL = "https://www.ccgp-shaanxi.gov.cn/freecms/site/shanxi/jdgl/index.html"


async def crawl_shaanxi_with_playwright() -> list[dict]:
    """使用 Playwright 爬取陕西政府采购网投诉处理列表（JS动态加载）

    调用生产纯解析函数 parse_shaanxi_list_html(html)。
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("playwright 未安装，跳过陕西采集")
        return []

    items: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(SHAANXI_TS_URL, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
            # 点击"投诉处理"标签（如果有）
            try:
                tab = page.locator("a:has-text('投诉处理')")
                if await tab.count() > 0:
                    await tab.first.click()
                    await asyncio.sleep(2)
            except Exception:
                pass
            html = await page.content()
            # 使用统一生产解析器 parse_shaanxi_list_html
            items = parse_shaanxi_list_html(html)
        except Exception as e:
            logger.error("陕西 Playwright 采集异常: %s", e)
        finally:
            await browser.close()
    return items


async def crawl_shaanxi() -> dict:
    """陕西采集入口 — Phase 1：使用 SafeFetcher（HTTPS-only + TLS 校验 + 域名白名单）

    Returns:
        dict with {"saved": int, "parsed_count": int, "completeness_sum": float}
        兼容旧调用方（历史上只消费 saved 字段）。
    """
    items = await crawl_shaanxi_with_playwright()
    if not items:
        return {"saved": 0, "parsed_count": 0, "completeness_sum": 0.0}
    saved = 0
    parsed_count = 0
    completeness_sum = 0.0
    from app.services.safe_fetcher import fetcher_for_source

    async with fetcher_for_source("shaanxi") as fetcher:
        for item in items[:10]:
            try:
                d = await crawl_ccgp_detail(item["url"], fetcher)
                if d:
                    d["province"] = "陕西"
                    parsed_count += 1
                    completeness_sum += pc(d, "shaanxi")
                    if _save_case(d):
                        saved += 1
            except Exception as e:
                logger.error("陕西详情采集失败 %s: %s", item["url"], e)
            await asyncio.sleep(0.5)
    return {"saved": saved, "parsed_count": parsed_count, "completeness_sum": completeness_sum}


import httpx  # noqa: E402
# ── 陕西/青海/新疆 Scrapling 入口（fallback）───────────────


async def crawl_with_scrapling(url: str, province: str) -> int:
    """通用 Scrapling 入口 — 使用已安装的 Scrapling MCP 工具抓取"""
    # 此函数作为占位符，Scrapling 是 MCP 工具而非 Python 库，
    # 供外部分析流程调用，不依赖额外依赖
    logger.info("Scrapling 采集占位: province=%s url=%s", province, url)
    return 0
