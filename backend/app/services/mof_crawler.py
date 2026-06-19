"""财政部信息公告爬虫 — 第3180-3362号系列"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.services.crawler_service import (
    _save_case,
    _extract_field,
    DECISION_TYPE_MAP,
)

logger = logging.getLogger(__name__)

# Phase 1 安全基线：只允许 HTTPS。HTTP fallback 已移除。
MOF_GK_LISTS = [
    "https://gks.mof.gov.cn/ztztz/zhengfucaigouguanli/",
]
MOF_GK_BASE = "https://gks.mof.gov.cn"


async def fetch_gks_list(fetcher) -> list[dict]:
    """获取财政部国库司政府采购管理页面最新公告列表
    Phase 1：HTTPS-only；使用 SafeFetcher（TLS + 域名白名单 + DNS 私网校验）。
    """
    items: list[dict] = []
    for list_url in MOF_GK_LISTS:
        try:
            html = await fetcher.get(list_url, source="mof")
            soup = BeautifulSoup(html, "lxml")
            for a_tag in soup.find_all("a", href=True):
                title = a_tag.get_text(strip=True)
                if "政府采购信息公告" not in title:
                    continue
                href = a_tag["href"]
                if href.startswith("./"):
                    href = MOF_GK_BASE + href[1:]
                elif href.startswith("/"):
                    href = MOF_GK_BASE + href
                elif not href.startswith("http"):
                    href = MOF_GK_BASE + "/" + href.lstrip("/")
                items.append({"title": title, "url": href})
            break  # 成功则退出循环
        except Exception as e:
            logger.warning("财政部列表抓取失败 %s: %s", list_url, e)
    return items


async def fetch_ccgp_gg_list(fetcher) -> list[dict]:
    """通过 ccgp.gov.cn/gg/ 获取财政部信息公告（较完整的列表）"""
    items: list[dict] = []
    for page in range(1, 6):  # 前5页
        url = f"https://www.ccgp.gov.cn/gg/index_{page}.htm"
        try:
            r = await client.get(url, timeout=30,
                                 headers={"User-Agent": "Mozilla/5.0"},
                                 follow_redirects=True)
            r.raise_for_status()
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for a_tag in soup.find_all("a", href=True):
            title = a_tag.get_text(strip=True)
            if "信息公告" not in title and "投诉处理" not in title:
                continue
            href = a_tag["href"]
            if href.startswith("./"):
                href = "https://www.ccgp.gov.cn" + href[1:]
            items.append({"title": title, "url": href})
    return items
