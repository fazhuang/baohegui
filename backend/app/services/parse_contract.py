"""纯解析函数 — 从 HTML 提取结构化数据

与网络请求完全解耦，供：
- crawler_service.py（线上爬虫）
- browser_crawler.py（Playwright 爬虫）
- test_source_fixtures.py（fixture 契约测试）

共用同一组纯函数，确保解析逻辑一致。结构漂移时 fixture 测试真实失败。
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

# ── 常量 ──────────────────────────────────────────────────────

CCGP_BASE = "https://www.ccgp.gov.cn"
NINGXIA_BASE = "https://www.ccgp-ningxia.gov.cn"
SHAANXI_BASE = "https://www.ccgp-shaanxi.gov.cn"
MOF_GK_BASE = "https://gks.mof.gov.cn"

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

COMPLAINT_KEYWORDS = [
    "参数", "品牌", "排他", "指向", "歧视", "授权", "检测报告", "资质",
    "中小企业", "虚假", "串通", "低价", "异常低价", "评分", "评审",
    "混包", "标准", "进口", "认证", "业绩", "售后",
]

# ── 来源元数据（每个来源的必填字段定义）──────────────────────────

SOURCE_META = {
    "ccgp": {
        "name": "CCGP 全国",
        "base_url": CCGP_BASE,
        "list_path": "jdjc/jdcf/",
        "version": "2.1.0",
        "parser_version": "2.0.0",
        "default_province": "全国",
        "required_fields": [
            "title", "source_url", "province", "decision_type",
            "decision_date", "summary",
        ],
    },
    "ningxia": {
        "name": "宁夏政府采购网",
        "base_url": NINGXIA_BASE,
        "list_path": "public/NXGPPNEW/dynamic/contents/TSCL/",
        "version": "2.1.0",
        "parser_version": "2.0.0",
        "default_province": "宁夏",
        "required_fields": [
            "title", "source_url", "province", "decision_type",
            "decision_date", "summary",
        ],
    },
    "shaanxi": {
        "name": "陕西政府采购网",
        "base_url": SHAANXI_BASE,
        "list_path": "freecms/site/shanxi/jdgl/",
        "version": "2.0.0",
        "parser_version": "1.5.0",
        "default_province": "陕西",
        "required_fields": [
            "title", "source_url", "province", "decision_type",
            "decision_date", "summary",
        ],
    },
    "mof": {
        "name": "财政部国库司",
        "base_url": MOF_GK_BASE,
        "list_path": "ztztz/zhengfucaigouguanli/",
        "version": "2.0.0",
        "parser_version": "1.5.0",
        "default_province": "全国",
        "required_fields": [
            "title", "source_url", "province", "decision_type",
            "summary",
        ],
    },
}


# ── 工具函数 ──────────────────────────────────────────────────


def extract_decision_type(text: str) -> str:
    """从处理结果中提取决定类型（纯函数，无副作用）。"""
    for keyword, dtype in DECISION_TYPE_MAP.items():
        if keyword in text:
            return dtype
    return "dismissed"


def extract_field(text: str, label: str, max_chars: int = 500) -> str:
    """从文本中提取指定标签后的内容（纯函数）。"""
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


def extract_date(text: str) -> str:
    """从文本中提取日期（纯函数），返回 YYYY-MM-DD 或空字符串。"""
    decision_date = ""
    for date_m in re.finditer(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text):
        decision_date = f"{date_m.group(1)}-{date_m.group(2).zfill(2)}-{date_m.group(3).zfill(2)}"
    return decision_date


def extract_complaint_keywords(text: str) -> list[str]:
    """从文本提取投诉类型关键词（纯函数）。"""
    return [kw for kw in COMPLAINT_KEYWORDS if kw in text]


# ── 列表页解析（纯函数 — 输入 HTML 字符串，输出结构化条目） ──


def parse_ccgp_list_html(html: str) -> list[dict]:
    """解析 CCGP 全国监督处罚列表页 HTML → [{title, url, date}]"""
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen_hrefs: set[str] = set()

    for ul in soup.find_all("ul"):
        for li in ul.find_all("li", recursive=False):
            a_tag = li.find("a")
            if not a_tag or not a_tag.get("href"):
                continue
            href = a_tag["href"]
            if not href.startswith("./20"):
                continue
            title = a_tag.get_text(strip=True)
            if "投诉" not in title:
                continue
            span = li.find("span")
            date_text = span.get_text(strip=True) if span else ""
            full_href = CCGP_BASE + "/jdjc/jdcf" + href[1:]
            if full_href in seen_hrefs:
                continue
            seen_hrefs.add(full_href)
            items.append({"title": title, "url": full_href, "date": date_text})
    return items


def parse_ningxia_list_html(html: str) -> list[dict]:
    """解析宁夏投诉处理列表页 HTML → [{title, url, date}]"""
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen_urls: set[str] = set()

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


def parse_shaanxi_list_html(html: str) -> list[dict]:
    """解析陕西投诉处理列表页 HTML → [{title, url, date}]"""
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []

    for link_tag in soup.select("a[href*='ggxx/info']"):
        title = link_tag.get_text(strip=True)
        if "投诉" not in title:
            continue
        href = link_tag.get("href", "")
        if href.startswith("/"):
            href = f"{SHAANXI_BASE}{href}"
        items.append({"title": title, "url": href, "date": ""})
    return items


def parse_mof_list_html(html: str, base_url: str = MOF_GK_BASE) -> list[dict]:
    """解析财政部列表页 HTML → [{title, url}]"""
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []

    for a_tag in soup.find_all("a", href=True):
        title = a_tag.get_text(strip=True)
        if "政府采购信息公告" not in title and "投诉处理" not in title:
            continue
        href = a_tag["href"]
        if href.startswith("./"):
            href = base_url + href[1:]
        elif href.startswith("/"):
            href = base_url + href
        items.append({"title": title, "url": href})
    return items


# ── 详情页解析（纯函数 — 输入 HTML + URL，输出结构化 dict） ──


def parse_detail_html(
    html: str,
    url: str = "",
    *,
    province: str = "全国",
) -> dict:
    """从详情页 HTML 解析结构化字段（纯函数，无网络 I/O）。

    Returns:
        与 crawl_ccgp_detail 相同结构的 dict，可直接传给 _save_case()。
    """
    soup = BeautifulSoup(html, "lxml")

    # ── 正文提取 ──────────────────────────────────────────
    raw_text = ""
    for sel in ["#main_contain", ".main-content", "article", ".article", ".content"]:
        div = soup.select_one(sel)
        if div:
            for aside in div.select(".sidebar, #sidebar, .aside, .right, .related, .nav, .navbar, .breadcrumb"):
                aside.decompose()
            raw_text = div.get_text("\n", strip=True)
            if len(raw_text.strip()) > 200:
                break

    if not raw_text or len(raw_text.strip()) < 100:
        for td in soup.find_all("td"):
            txt = td.get_text("\n", strip=True)
            if "项目编号" in txt or "项目名称" in txt:
                raw_text = txt
                break

    if not raw_text.strip():
        body = soup.find("body")
        raw_text = body.get_text("\n", strip=True) if body else ""

    # ── 标题 ──────────────────────────────────────────────
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    if title in ("投诉处理", "") or "当前位置" in title:
        for line in raw_text.split("\n"):
            if "政府采购投诉" in line or "投诉处理结果公告" in line:
                title = line.strip()[:200]
                break

    # ── 字段提取 ──────────────────────────────────────────
    project_name = extract_field(raw_text, "项目名称")
    project_number = extract_field(raw_text, "项目编号")
    complainant = extract_field(raw_text, "投诉人", 300)
    decision_date = extract_date(raw_text)

    # ── 结果段 + 决定类型 ─────────────────────────────────
    result_section = ""
    result_match = re.search(
        r"(?:五、处理依据及结果|五、处理依据|处理依据及结果|处理决定)(.*?)(?:六、|七、|$)",
        raw_text, re.DOTALL,
    )
    if result_match:
        result_section = result_match.group(1).strip()[:800]

    decision_type = extract_decision_type(result_section or raw_text)
    complaint_kw = extract_complaint_keywords(raw_text)

    return {
        "province": province,
        "source_url": url,
        "title": title[:200] if title else "",
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


# ── 字段完整率计算（纯函数）──────────────────────────────────


def _check_required_fields(data: dict, source: str) -> dict:
    """检查必填字段完整率。返回 {field: True/False}。

    供 crawler_service.py 生产路径和 test_source_fixtures.py 测试路径共用。
    """
    meta = SOURCE_META.get(source, SOURCE_META["ccgp"])
    return {f: bool(data.get(f)) for f in meta["required_fields"]}


def _compute_completeness(data: dict, source: str) -> float:
    """计算字段完整率 (0.0–1.0)。

    基于该来源的 required_fields 真实计算，非 saved/fetched 比值。
    供 crawler_service.py 生产路径和 test_source_fixtures.py 测试路径共用。
    """
    checks = _check_required_fields(data, source)
    if not checks:
        return 0.0
    return sum(1 for v in checks.values() if v) / len(checks)
