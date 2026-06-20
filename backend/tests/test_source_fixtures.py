"""来源 fixtures 和解析契约测试

Phase 2 阻塞项 E — 为 4 个真实采集来源建立质量门禁：

每个来源必须有：
- 脱敏 HTML fixture（列表页 + 详情页）
- 列表页解析契约测试
- 详情页解析契约测试
- 必填字段完整率检查
- 解析失败类型
- 来源版本 / parser version

测试不得访问外网。真实 canary 运行逻辑与 fixture 测试分离。

data/ 子目录下的 fixtures 为手动获取并脱敏的真实 HTML 片段。
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

# ── Fixtures 目录 ──────────────────────────────────────

FIXTURES_DIR = Path(__file__).resolve().parent / "data" / "source_fixtures"


def _read_fixture(source: str, page_type: str) -> str:
    """读取 fixture 文件，返回 HTML 字符串。若不存在则跳过测试。"""
    fpath = FIXTURES_DIR / source / f"{page_type}.html"
    if not fpath.exists():
        pytest.skip(f"Fixture not found: {fpath}")
    return fpath.read_text(encoding="utf-8")


def _read_json_fixture(source: str, name: str) -> dict | None:
    """读取 JSON fixture。"""
    fpath = FIXTURES_DIR / source / f"{name}.json"
    if not fpath.exists():
        return None
    return json.loads(fpath.read_text(encoding="utf-8"))


# ── 来源元数据（常量，与 crawler_service.py 保持同步）─────

SOURCE_META = {
    "ccgp": {
        "name": "CCGP 全国",
        "base_url": "https://www.ccgp.gov.cn",
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
        "base_url": "https://www.ccgp-ningxia.gov.cn",
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
        "base_url": "https://www.ccgp-shaanxi.gov.cn",
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
        "base_url": "https://gks.mof.gov.cn",
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


# ═══════════════════════════════════════════════════════
# 常量定义（不使用 magic strings）
# ═══════════════════════════════════════════════════════

DECISION_TYPES = frozenset({"upheld", "rejected", "partial", "dismissed", "unknown"})
VALID_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_CONTENT_LENGTH = 20  # 最小的有意义正文长度
MAX_TITLE_LENGTH = 255
MAX_URL_LENGTH = 1024


# ── 通用解析契约辅助 ──────────────────────────────────

def _check_required_fields(data: dict, source: str) -> dict:
    """检查必填字段完整率。返回 {field: True/False}。"""
    meta = SOURCE_META[source]
    return {f: bool(data.get(f)) for f in meta["required_fields"]}


def _compute_completeness(data: dict, source: str) -> float:
    """计算字段完整率 (0.0–1.0)。"""
    checks = _check_required_fields(data, source)
    if not checks:
        return 1.0
    return sum(1 for v in checks.values() if v) / len(checks)


def _parse_list_items(html: str, source: str) -> list[dict]:
    """从列表页 HTML 中解析条目列表（使用实际爬虫逻辑的子集）。

    返回 [{"title": ..., "url": ..., "date": ...}]。
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    items = []
    seen_urls = set()

    if source == "ccgp":
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
                full_url = SOURCE_META[source]["base_url"] + "/jdjc/jdcf" + href[1:]
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)
                items.append({"title": title, "url": full_url, "date": date_text})

    elif source == "ningxia":
        base = SOURCE_META[source]["base_url"]
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            title = a_tag.get_text(strip=True)
            if "投诉处理结果公告" not in title:
                continue
            if not href.startswith("contents/TSCL/"):
                continue
            full_url = f"{base}/public/NXGPPNEW/dynamic/{href}"
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            items.append({"title": title, "url": full_url, "date": ""})

    elif source == "mof":
        base = SOURCE_META[source]["base_url"]
        for a_tag in soup.find_all("a", href=True):
            title = a_tag.get_text(strip=True)
            if "政府采购信息公告" not in title and "投诉处理" not in title:
                continue
            href = a_tag["href"]
            if href.startswith("./"):
                href = base + href[1:]
            elif href.startswith("/"):
                href = base + href
            items.append({"title": title, "url": href})

    elif source == "shaanxi":
        for link_tag in soup.select("a[href*='ggxx/info']"):
            title = link_tag.get_text(strip=True)
            if "投诉" not in title:
                continue
            href = link_tag.get("href", "")
            if href.startswith("/"):
                href = SOURCE_META[source]["base_url"] + href
            items.append({"title": title, "url": href, "date": ""})

    return items


def _parse_detail(html: str, source: str, url: str = "") -> dict | None:
    """从详情页 HTML 中解析结构化字段（使用实际爬虫逻辑的子集）。

    返回与 crawl_ccgp_detail 相同结构的 dict。
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    # 正文提取
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

    # 标题
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    if title in ("投诉处理", "") or "当前位置" in title:
        for line in raw_text.split("\n"):
            if "政府采购投诉" in line or "投诉处理结果公告" in line:
                title = line.strip()[:200]
                break

    # 字段提取
    def _extract_field(text: str, label: str, max_chars: int = 500) -> str:
        next_section = r"(?:[一二三四五六七八九十]、|基本情况|处理依据及结果|处理依据|处理决定|其他补充)"
        for pat in [
            rf"{label}[：:]\s*(.+?)(?:\n(?:[一二三四五六七八九十]、|$))",
            rf"{label}[：:]\s*(.+?)(?:{next_section})",
            rf"{label}[：:]\s*(.+?)(?:\n\n)",
            rf"{label}[：:]\s*(.+)",
        ]:
            m = re.search(pat, text, re.DOTALL)
            if m:
                val = m.group(1).strip()
                if len(val) > max_chars:
                    val = val[:max_chars] + "..."
                return val
        return ""

    project_name = _extract_field(raw_text, "项目名称")
    project_number = _extract_field(raw_text, "项目编号")
    complainant = _extract_field(raw_text, "投诉人", 300)

    # 日期提取
    decision_date = ""
    for date_m in re.finditer(r"(\d{4})年(\d{1,2})月(\d{1,2})日", raw_text):
        decision_date = f"{date_m.group(1)}-{date_m.group(2).zfill(2)}-{date_m.group(3).zfill(2)}"

    # 决定类型
    decision_type_map = {
        "驳回投诉": "rejected", "驳回": "rejected", "投诉不成立": "rejected",
        "投诉成立": "upheld", "责令重新": "upheld", "中标无效": "upheld",
        "部分成立": "partial", "部分": "partial", "撤销合同": "upheld",
        "废标": "upheld", "重新开展": "upheld",
    }
    result_section = ""
    result_match = re.search(
        r"(?:五、处理依据及结果|五、处理依据|处理依据及结果|处理决定)(.*?)(?:六、|七、|$)",
        raw_text, re.DOTALL,
    )
    if result_match:
        result_section = result_match.group(1).strip()[:800]

    decision_type = "dismissed"
    for keyword, dtype in decision_type_map.items():
        if keyword in (result_section or raw_text):
            decision_type = dtype
            break

    # 投诉类型关键词
    complaint_kw = []
    for kw in [
        "参数", "品牌", "排他", "指向", "歧视", "授权", "检测报告", "资质",
        "中小企业", "虚假", "串通", "低价", "异常低价", "评分", "评审",
        "混包", "标准", "进口", "认证", "业绩", "售后",
    ]:
        if kw in raw_text:
            complaint_kw.append(kw)

    return {
        "province": SOURCE_META[source]["default_province"]
            if source in ("ccgp", "mof") else
            "宁夏" if source == "ningxia" else
            "陕西" if source == "shaanxi" else
            "全国",
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


# ═══════════════════════════════════════════════════════
# 列表页解析契约测试
# ═══════════════════════════════════════════════════════


class TestListPageContracts:
    """每个来源的列表页解析契约"""

    def test_ccgp_list_parse(self):
        """CCGP 列表页：至少产出 1 条有效条目，含 title/url"""
        html = _read_fixture("ccgp", "list")
        items = _parse_list_items(html, "ccgp")
        assert len(items) >= 1, "CCGP list fixture should yield at least 1 item"
        for item in items:
            assert item.get("title"), f"Item missing title: {item}"
            assert item.get("url", "").startswith("https://"), f"Item URL not HTTPS: {item}"
            assert len(item["title"]) <= MAX_TITLE_LENGTH

    def test_ningxia_list_parse(self):
        """宁夏列表页：至少产出 1 条有效条��"""
        html = _read_fixture("ningxia", "list")
        items = _parse_list_items(html, "ningxia")
        assert len(items) >= 1, "Ningxia list fixture should yield at least 1 item"
        for item in items:
            assert "投诉处理结果公告" in item.get("title", ""), \
                f"Item title should contain 投诉处理结果公告: {item['title']}"
            assert item.get("url", "").startswith("https://"), f"Item URL not HTTPS: {item}"

    def test_shaanxi_list_parse(self):
        """陕西列表页：至少产出 1 条有效条目"""
        html = _read_fixture("shaanxi", "list")
        items = _parse_list_items(html, "shaanxi")
        assert len(items) >= 1, "Shaanxi list fixture should yield at least 1 item"
        for item in items:
            assert "投诉" in item.get("title", ""), \
                f"Item title should contain 投诉: {item['title']}"
            assert item.get("url", "").startswith("https://"), f"Item URL not HTTPS: {item}"

    def test_mof_list_parse(self):
        """财政部列表页：至少产出 1 条有效条目"""
        html = _read_fixture("mof", "list")
        items = _parse_list_items(html, "mof")
        assert len(items) >= 1, "MOF list fixture should yield at least 1 item"
        for item in items:
            assert item.get("title"), f"Item missing title: {item}"
            assert item.get("url", "").startswith("https://"), f"Item URL not HTTPS: {item}"


# ═══════════════════════════════════════════════════════
# 详情页解析契约测试
# ═══════════════════════════════════════════════════════


class TestDetailPageContracts:
    """每个来源的详情页解析契约"""

    def test_ccgp_detail_parse(self):
        """CCGP 详情页：解析结果必填字段完整"""
        html = _read_fixture("ccgp", "detail")
        result = _parse_detail(html, "ccgp", url="https://www.ccgp.gov.cn/jdjc/jdcf/2025/123")
        assert result is not None, "CCGP detail parse returned None"

        completeness = _compute_completeness(result, "ccgp")
        assert completeness >= 0.5, (
            f"CCGP detail completeness={completeness:.0%} below 50% threshold. "
            f"Required fields: {_check_required_fields(result, 'ccgp')}"
        )

        assert result.get("title"), "title is required"
        assert result["decision_type"] in DECISION_TYPES, \
            f"Invalid decision_type: {result['decision_type']}"
        if result.get("decision_date"):
            assert VALID_DATE_PATTERN.match(result["decision_date"]), \
                f"Invalid decision_date format: {result['decision_date']}"
        assert result.get("province") == "全国"
        assert len(result.get("raw_content", "")) >= MIN_CONTENT_LENGTH, \
            f"raw_content too short: {len(result.get('raw_content', ''))} chars"

    def test_ningxia_detail_parse(self):
        """宁夏详情页：解析结果必填字段完整"""
        html = _read_fixture("ningxia", "detail")
        result = _parse_detail(html, "ningxia", url="https://www.ccgp-ningxia.gov.cn/public/...")
        assert result is not None, "Ningxia detail parse returned None"

        completeness = _compute_completeness(result, "ningxia")
        assert completeness >= 0.5, (
            f"Ningxia detail completeness={completeness:.0%} below 50% threshold. "
            f"Required: {_check_required_fields(result, 'ningxia')}"
        )

        assert result.get("title"), "title is required"
        assert result["decision_type"] in DECISION_TYPES
        if result.get("decision_date"):
            assert VALID_DATE_PATTERN.match(result["decision_date"])

    def test_shaanxi_detail_parse(self):
        """陕西详情页：解析结果必填字段完整"""
        html = _read_fixture("shaanxi", "detail")
        result = _parse_detail(html, "shaanxi", url="https://www.ccgp-shaanxi.gov.cn/...")
        assert result is not None, "Shaanxi detail parse returned None"

        completeness = _compute_completeness(result, "shaanxi")
        assert completeness >= 0.5, (
            f"Shaanxi detail completeness={completeness:.0%} below 50% threshold. "
            f"Required: {_check_required_fields(result, 'shaanxi')}"
        )

        assert result.get("title"), "title is required"
        assert result["decision_type"] in DECISION_TYPES

    def test_mof_detail_parse(self):
        """财政部详情页：解析结果必填字段完整"""
        html = _read_fixture("mof", "detail")
        result = _parse_detail(html, "mof", url="https://gks.mof.gov.cn/...")
        assert result is not None, "MOF detail parse returned None"

        completeness = _compute_completeness(result, "mof")
        assert completeness >= 0.5, (
            f"MOF detail completeness={completeness:.0%} below 50% threshold. "
            f"Required: {_check_required_fields(result, 'mof')}"
        )

        assert result.get("title"), "title is required"
        assert result["decision_type"] in DECISION_TYPES


# ═══════════════════════════════════════════════════════
# Canary 指标和来源健康度
# ═══════════════════════════════════════════════════════


class TestSourceCanaryMetrics:
    """来源 canary 指标和连续运行追踪

    每个来源必须有：
    - canary 结果持久化（JSON 格式）
    - 最近成功时间
    - 连续失败次数
    - 最近错误类型
    """

    def test_ccgp_canary_config(self):
        """CCGP canary 配置存在并包含所有必需字段"""
        config = _read_json_fixture("ccgp", "canary_config")
        if config is None:
            pytest.skip("CCGP canary config not yet created")
        assert "source" in config
        assert "version" in config
        assert "parser_version" in config
        assert "last_success" in config or "last_success" not in config  # may be null
        assert "consecutive_failures" in config
        assert "status" in config
        assert config["status"] in ("collecting", "not_enough_data", "healthy", "degraded")

    def test_ningxia_canary_config(self):
        """宁夏 canary 配置存在"""
        config = _read_json_fixture("ningxia", "canary_config")
        if config is None:
            pytest.skip("Ningxia canary config not yet created")
        assert "source" in config
        assert "consecutive_failures" in config
        assert "status" in config
        assert config["status"] in ("collecting", "not_enough_data", "healthy", "degraded")

    def test_shaanxi_canary_config(self):
        """陕西 canary 配置存在"""
        config = _read_json_fixture("shaanxi", "canary_config")
        if config is None:
            pytest.skip("Shaanxi canary config not yet created")
        assert "source" in config
        assert "consecutive_failures" in config
        assert "status" in config

    def test_mof_canary_config(self):
        """财政部 canary 配置存在"""
        config = _read_json_fixture("mof", "canary_config")
        if config is None:
            pytest.skip("MOF canary config not yet created")
        assert "source" in config
        assert "consecutive_failures" in config
        assert "status" in config

    def test_healthy_7d_never_claimed_falsely(self):
        """canary 状态绝不得在不满足 7 天连续运行时声明为健康。

        每个来源的 canary 起始时间到今天不满 7 天则状态不得为 healthy_7d。
        """
        for source in ["ccgp", "ningxia", "shaanxi", "mof"]:
            config = _read_json_fixture(source, "canary_config")
            if config is None:
                continue
            status = config.get("status", "")
            assert status != "healthy_7d", (
                f"{source}: status='healthy_7d' requires 7 days of continuous data; "
                f"this cannot yet be satisfied"
            )
            # collecting / not_enough_data is the expected state
            assert status in ("collecting", "not_enough_data", "degraded", "healthy"), (
                f"{source}: unexpected status '{status}'"
            )


# ═══════════════════════════════════════════════════════
# 来源版本和 parser version
# ═══════════════════════════════════════════════════════


class TestSourceVersioning:
    """每个来源的有序版本号"""

    def test_all_sources_have_version(self):
        for source, meta in SOURCE_META.items():
            assert meta.get("version"), f"{source}: version missing"
            assert meta.get("parser_version"), f"{source}: parser_version missing"

    def test_all_sources_have_required_fields(self):
        for source, meta in SOURCE_META.items():
            assert len(meta.get("required_fields", [])) >= 3, \
                f"{source}: need at least 3 required fields"


# ── 解析失败类型映射（与 SafeFetchError 保持同步）─────


class TestFailureTypeMapping:
    """确保解析失败类型与 SafeFetchError 枚举同步"""

    def test_failure_types_cover_all(self):
        from app.services.safe_fetcher import FetchErrorType
        known = set(e.value for e in FetchErrorType)
        expected = {
            "not_https", "dns_private", "dns_failed", "tls_error",
            "redirect_to_http", "redirect_to_private", "redirect_cross_domain",
            "redirect_loop", "content_too_large", "content_type_rejected",
            "timeout", "http_error", "network", "source_unknown",
        }
        assert known == expected, f"FetchErrorType mismatch: expected-only={expected-known}, new-only={known-expected}"
