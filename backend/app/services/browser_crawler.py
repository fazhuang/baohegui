"""Playwright浏览器爬虫 — 处理陕西/青海/新疆等需要JS渲染的政府采购网"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from app.services.crawler_service import (
    _save_case,
    crawl_ccgp_detail,
    DECISION_TYPE_MAP,
)

logger = logging.getLogger(__name__)

# ── 陕西 ──────────────────────────────────────────────────────

SHAANXI_TS_URL = "https://www.ccgp-shaanxi.gov.cn/freecms/site/shanxi/jdgl/index.html"


async def crawl_shaanxi_with_playwright() -> list[dict]:
    """使用 Playwright 爬取陕西政府采购网投诉处理列表（JS动态加载）"""
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
            soup = BeautifulSoup(html, "lxml")
            for link_tag in soup.select("a[href*='ggxx/info']"):
                title = link_tag.get_text(strip=True)
                if "投诉" not in title:
                    continue
                href = link_tag.get("href", "")
                if href.startswith("/"):
                    href = f"https://www.ccgp-shaanxi.gov.cn{href}"
                items.append({"title": title, "url": href, "date": ""})
        except Exception as e:
            logger.error("陕西 Playwright 采集异常: %s", e)
        finally:
            await browser.close()
    return items


async def crawl_shaanxi() -> int:
    """陕西采集入口"""
    items = await crawl_shaanxi_with_playwright()
    if not items:
        return 0
    saved = 0
    async with httpx.AsyncClient(verify=False) as client:
        for item in items[:10]:
            d = await crawl_ccgp_detail(item["url"], client)
            if d:
                d["province"] = "陕西"
                if _save_case(d):
                    saved += 1
            await asyncio.sleep(0.5)
    return saved


import httpx  # noqa: E402


# ── 陕西/青海/新疆 Scrapling 入口（fallback）───────────────


async def crawl_with_scrapling(url: str, province: str) -> int:
    """通用 Scrapling 入口 — 使用已安装的 Scrapling MCP 工具抓取"""
    # 此函数作为占位符，Scrapling 是 MCP 工具而非 Python 库，
    # 供外部分析流程调用，不依赖额外依赖
    logger.info("Scrapling 采集占位: province=%s url=%s", province, url)
    return 0
