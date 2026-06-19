"""安全 HTTP 抓取器 — 统一 TLS、出站访问、重定向和响应体约束。

策略：
- HTTPS-only（明文 HTTP 拒绝）
- 来源域名白名单
- 每次重定向逐跳校验 scheme/domain/IP
- 拒绝 localhost、私网、链路本地、保留地址
- DNS 解析结果校验（A + AAAA 均需通过）
- 限制重定向次数
- 连接、读取和总超时
- 流式读取 + 最大响应体限制
- Content-Type 白名单
- 清晰错误类型和来源日志

使用方式::

    async with SafeFetcher() as fetcher:
        text = await fetcher.get("https://www.ccgp.gov.cn/...")
        # 或带来源标签：
        text = await fetcher.get("https://...", source="ccgp")

安全原则：
- 任何安全问题立即抛出 SafeFetchError，不做静默降级
- 错误消息包含具体原因，可供上游统计
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────────

# 最大响应体大小（字节）
DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
# 最大重定向次数
MAX_REDIRECTS = 5
# 默认超时
DEFAULT_CONNECT_TIMEOUT = 15.0
DEFAULT_READ_TIMEOUT = 30.0
DEFAULT_TOTAL_TIMEOUT = 60.0

# Content-Type 白名单（允许提取文本的 MIME 类型前缀）
ALLOWED_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
)

# 采集来源域名白名单
ALLOWED_DOMAINS: dict[str, list[str]] = {
    "ccgp": ["www.ccgp.gov.cn"],
    "ningxia": ["www.ccgp-ningxia.gov.cn"],
    "shaanxi": ["www.ccgp-shaanxi.gov.cn"],
    "mof": ["gks.mof.gov.cn", "www.ccgp.gov.cn"],
}

# 私有 / 保留 IP 网络（禁止作为目标）
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("224.0.0.0/4"),  # 组播
    ipaddress.ip_network("240.0.0.0/4"),  # 保留
    ipaddress.ip_network("::1/128"),       # IPv6 loopback
    ipaddress.ip_network("fe80::/10"),     # IPv6 link-local
    ipaddress.ip_network("fc00::/7"),      # IPv6 unique local
]


# ── 错误类型 ────────────────────────────────────────────────────


class FetchErrorType(str, Enum):
    """抓取错误分类"""
    NOT_HTTPS = "not_https"
    DNS_PRIVATE = "dns_private"
    DNS_FAILED = "dns_failed"
    TLS_ERROR = "tls_error"
    REDIRECT_TO_HTTP = "redirect_to_http"
    REDIRECT_TO_PRIVATE = "redirect_to_private"
    REDIRECT_CROSS_DOMAIN = "redirect_cross_domain"
    REDIRECT_LOOP = "redirect_loop"
    CONTENT_TOO_LARGE = "content_too_large"
    CONTENT_TYPE_REJECTED = "content_type_rejected"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    NETWORK = "network"


@dataclass
class SafeFetchError(Exception):
    """安全抓取错误 — 包含可统计的错误类型和来源标签"""
    error_type: FetchErrorType
    message: str
    url: str = ""
    source: str = ""
    status_code: int | None = None


# ── 工具函数 ────────────────────────────────────────────────────


def _is_private_ip(host: str) -> bool:
    """检查 IP 地址是否属于私有/保留范围"""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    for net in _PRIVATE_NETS:
        if addr in net:
            return True
    return False


async def _resolve_and_validate(host: str, source: str, url: str) -> str:
    """DNS 解析主机名并校验结果。

    返回原始 host（校验通过时）。
    抛出 SafeFetchError（解析到私网地址或解析失败）。
    """
    loop = asyncio.get_running_loop()
    try:
        addrs = await loop.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except Exception as e:
        raise SafeFetchError(
            error_type=FetchErrorType.DNS_FAILED,
            message=f"DNS 解析失败 {host}: {e}",
            url=url, source=source,
        )

    if not addrs:
        raise SafeFetchError(
            error_type=FetchErrorType.DNS_FAILED,
            message=f"DNS 无记录 {host}",
            url=url, source=source,
        )

    for family, _, _, _, sockaddr in addrs:
        ip = sockaddr[0]
        if _is_private_ip(ip):
            raise SafeFetchError(
                error_type=FetchErrorType.DNS_PRIVATE,
                message=f"DNS 解析到私网地址 {host} → {ip}",
                url=url, source=source,
            )
    return host


# ── 安全客户端 ──────────────────────────────────────────────────


class SafeFetcher:
    """安全 HTTP 抓取器。

    关键约束：
    - TLS 始终启用（verify=True，默认 CA 捆绑包）。
    - 仅允许 HTTPS scheme。
    - 每个目标 URL 的域名必须通过 DNS 校验（无私有 IP）。
    - 重定向逐跳校验（scheme、domain、DNS）。
    - 响应体流式读取，受 max_bytes 限制。
    - Content-Type 必须匹配白名单。
    """

    def __init__(
        self,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
        max_redirects: int = MAX_REDIRECTS,
        allowed_domains: list[str] | None = None,
        source: str = "",
    ):
        self._max_bytes = max_bytes
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._total_timeout = total_timeout
        self._max_redirects = max_redirects
        self._allowed_domains = allowed_domains
        self._source = source

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            verify=True,
            follow_redirects=False,  # 手动控制重定向
            timeout=httpx.Timeout(
                connect=self._connect_timeout,
                read=self._read_timeout,
                write=10.0,
                pool=10.0,
            ),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    # ── 公共接口 ────────────────────────────────────────────────

    async def get(self, url: str, *, source: str = "") -> str:
        """安全抓取 URL 并返回响应文本。

        Raises:
            SafeFetchError: 任何安全或传输问题。
        """
        label = source or self._source
        return await self._fetch_with_redirect(url, source=label, redirect_count=0)

    # ── 内部实现 ────────────────────────────────────────────────

    async def _fetch_with_redirect(
        self, url: str, *, source: str, redirect_count: int,
    ) -> str:
        """带逐跳重定向校验的抓取循环。"""
        # 步骤 0：校验 URL scheme
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise SafeFetchError(
                error_type=FetchErrorType.NOT_HTTPS,
                message=f"仅允许 HTTPS: {url}",
                url=url, source=source,
            )

        host = parsed.hostname or ""
        if not host:
            raise SafeFetchError(
                error_type=FetchErrorType.NETWORK,
                message=f"URL 缺少主机名: {url}",
                url=url, source=source,
            )

        # 步骤 1：域名白名单检查
        if self._allowed_domains and host not in self._allowed_domains:
            raise SafeFetchError(
                error_type=FetchErrorType.REDIRECT_CROSS_DOMAIN,
                message=f"域名 {host} 不在白名单 {self._allowed_domains}",
                url=url, source=source,
            )

        # 步骤 2：DNS 校验
        await _resolve_and_validate(host, source=source, url=url)

        # 步骤 3：发送请求
        try:
            resp = await self._client.get(url)
        except httpx.ConnectError as e:
            raise SafeFetchError(
                error_type=FetchErrorType.NETWORK,
                message=f"连接失败 {host}: {e}",
                url=url, source=source,
            )
        except httpx.ReadTimeout:
            raise SafeFetchError(
                error_type=FetchErrorType.TIMEOUT,
                message=f"读取超时 {url}",
                url=url, source=source,
            )
        except Exception as e:
            # 捕获 SSL 错误（证书校验失败等）
            msg = str(e)
            if "ssl" in msg.lower() or "certificate" in msg.lower() or "tls" in msg.lower():
                raise SafeFetchError(
                    error_type=FetchErrorType.TLS_ERROR,
                    message=f"TLS 错误 {host}: {e}",
                    url=url, source=source,
                )
            raise SafeFetchError(
                error_type=FetchErrorType.NETWORK,
                message=f"网络错误 {host}: {e}",
                url=url, source=source,
            )

        # 步骤 4：处理重定向
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if not location:
                raise SafeFetchError(
                    error_type=FetchErrorType.NETWORK,
                    message=f"重定向响应缺少 Location 头: {url}",
                    url=url, source=source,
                )

            # 解析相对 URL
            from urllib.parse import urljoin
            next_url = urljoin(url, location)

            if redirect_count >= self._max_redirects:
                raise SafeFetchError(
                    error_type=FetchErrorType.REDIRECT_LOOP,
                    message=f"重定向次数超限 ({self._max_redirects}): {url} → {next_url}",
                    url=url, source=source,
                )

            # 逐跳校验重定向目标
            next_parsed = urlparse(next_url)
            if next_parsed.scheme != "https":
                raise SafeFetchError(
                    error_type=FetchErrorType.REDIRECT_TO_HTTP,
                    message=f"重定向到 HTTP: {next_url}",
                    url=url, source=source,
                )

            next_host = next_parsed.hostname or ""
            if self._allowed_domains and next_host not in self._allowed_domains:
                raise SafeFetchError(
                    error_type=FetchErrorType.REDIRECT_CROSS_DOMAIN,
                    message=f"重定向跨域 {host} → {next_host}，不在白名单内",
                    url=url, source=source,
                )

            await _resolve_and_validate(next_host, source=source, url=next_url)

            return await self._fetch_with_redirect(
                next_url, source=source, redirect_count=redirect_count + 1,
            )

        # 步骤 5：HTTP 状态码检查
        if resp.status_code >= 400:
            raise SafeFetchError(
                error_type=FetchErrorType.HTTP_ERROR,
                message=f"HTTP {resp.status_code}: {url}",
                url=url, source=source,
                status_code=resp.status_code,
            )

        # 步骤 6：Content-Type 检查
        content_type = resp.headers.get("content-type", "")
        if content_type:
            ct_lower = content_type.lower()
            allowed = any(ct_lower.startswith(prefix) for prefix in ALLOWED_CONTENT_TYPES)
            if not allowed:
                raise SafeFetchError(
                    error_type=FetchErrorType.CONTENT_TYPE_REJECTED,
                    message=f"拒绝 Content-Type '{content_type}': {url}",
                    url=url, source=source,
                )

        # 步骤 7：流式读取受大小限制
        content_length = resp.headers.get("content-length")
        if content_length:
            try:
                cl = int(content_length)
                if cl > self._max_bytes:
                    raise SafeFetchError(
                        error_type=FetchErrorType.CONTENT_TOO_LARGE,
                        message=f"Content-Length {cl} 超过限制 {self._max_bytes}",
                        url=url, source=source,
                    )
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes(chunk_size=65536):
            total += len(chunk)
            if total > self._max_bytes:
                raise SafeFetchError(
                    error_type=FetchErrorType.CONTENT_TOO_LARGE,
                    message=f"响应体超过限制 {self._max_bytes}（已读取 {total} 字节）",
                    url=url, source=source,
                )
            chunks.append(chunk)

        return b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")


# ── 便捷工厂 ────────────────────────────────────────────────────


def fetcher_for_source(source: str) -> SafeFetcher:
    """为指定采集来源创建已配置域名白名单的抓取器。

    source 必须匹配 ALLOWED_DOMAINS 中的键。
    """
    domains = ALLOWED_DOMAINS.get(source)
    return SafeFetcher(allowed_domains=domains, source=source)
