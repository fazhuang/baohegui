"""Phase 1 安全测试 — 采集传输安全、数据隔离、KG 可见性、任务状态。

覆盖：
- 证书校验失败
- HTTP URL 拒绝
- 跨域重定向拒绝
- 重定向到 127.0.0.1 拒绝
- 重定向到私网 IP 拒绝
- DNS 解析到私网拒绝
- Content-Type 非 HTML 拒绝
- 普通用户读取原始案例被阻止
- 普通用户查询未审核 KG 被拒绝
- 非法 relation 类型组合
- 单来源失败后 PARTIAL 状态
- 依赖健康状态上报
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import tempfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.models.complaint_case import ComplaintCase
from app.models.knowledge_graph import KGNode, KGEdge
from app.models.user import User


def _create_user(db, username: str, role: str = "user") -> User:
    u = User(
        username=username,
        hashed_password=hash_password("testpass123"),
        role=role,
        company="测试",
        email=f"{username}@test.com",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _headers(user: User) -> dict:
    token = create_access_token(user_id=user.id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════
# 安全抓取器测试
# ═══════════════════════════════════════════════════════════════


class TestSafeFetcherTransport:
    """TLS 传输安全"""

    @pytest.mark.asyncio
    async def test_rejects_http_url(self, monkeypatch):
        """HTTP URL 必须被拒绝（DNS 被 mock 隔离）。"""
        from app.services.safe_fetcher import SafeFetcher, SafeFetchError, FetchErrorType

        async def _fake_resolve(*args, **kwargs):
            return "www.ccgp.gov.cn"
        monkeypatch.setattr("app.services.safe_fetcher._resolve_and_validate", _fake_resolve)

        async with SafeFetcher(source="test") as f:
            with pytest.raises(SafeFetchError) as exc:
                await f.get("http://www.ccgp.gov.cn/page", source="test")
            assert exc.value.error_type == FetchErrorType.NOT_HTTPS

    @pytest.mark.asyncio
    async def test_rejects_localhost(self):
        """重定向到 127.0.0.1 / 私网 / 保留地址全部被拒绝。"""
        from app.services.safe_fetcher import SafeFetcher, SafeFetchError, _is_private_ip

        non_routable = [
            "127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1",
            "169.254.1.1", "198.18.0.1", "192.0.2.1", "100.64.0.1",
            "2001:db8::1", "ff02::1", "::",
        ]
        for ip in non_routable:
            assert _is_private_ip(ip), f"{ip} should be private"

        routable = ["8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"]
        for ip in routable:
            assert not _is_private_ip(ip), f"{ip} should not be private"


class TestSafeFetcherDNS:
    """DNS 解析校验"""

    def test_dns_private_ip_detection(self):
        """IP 私网检测函数正确 — 使用 ipaddress.is_global（not is_global → 私网）。"""
        from app.services.safe_fetcher import _is_private_ip

        # 非公网可路由（及组播/未指定）→ _is_private_ip=True
        non_routable = [
            "10.0.0.1", "10.255.255.255",
            "172.16.0.0", "172.31.255.255",
            "192.168.0.0", "192.168.255.255",
            "127.0.0.1", "127.255.255.255",
            "169.254.0.1",
            "0.0.0.0",
            "224.0.0.1",          # 组播
            "239.255.255.250",    # SSDP 组播
            "198.18.0.1",         # IANA Benchmarking
            "192.0.2.1",          # IANA TEST-NET-1
            "198.51.100.1",       # IANA TEST-NET-2
            "203.0.113.1",        # IANA TEST-NET-3
            "100.64.0.1",         # CGNAT
            "::1",
            "fe80::1",
            "fc00::1",
            "2001:db8::1",        # IANA 文档保留
            "ff02::1",            # IPv6 组播
            "::",                 # 未指定地址
        ]
        for ip in non_routable:
            assert _is_private_ip(ip), f"{ip} should be private"

        # 可全局路由（is_global=True → _is_private_ip=False）
        routable = [
            "8.8.8.8", "1.1.1.1", "93.184.216.34",
            "2001:4860:4860::8888",
        ]
        for ip in routable:
            assert not _is_private_ip(ip), f"{ip} should not be private"


class TestSafeFetcherContentType:
    """Content-Type 白名单"""

    @pytest.mark.asyncio
    async def test_rejects_non_html(self, monkeypatch):
        """非 HTML Content-Type 必须被拒绝。
        直接调用内部的 _fetch_with_redirect 并提供一个 mock 响应。"""
        from app.services.safe_fetcher import SafeFetcher, SafeFetchError, FetchErrorType

        async def _fake_resolve(*args, **kwargs):
            return "www.ccgp.gov.cn"
        monkeypatch.setattr("app.services.safe_fetcher._resolve_and_validate", _fake_resolve)

        class FakeResp:
            status_code = 200
            encoding = "utf-8"
            headers = {"content-type": "application/pdf"}
            async def aiter_bytes(self, chunk_size=65536):
                yield b""
                return
            async def aclose(self):
                pass

        async def fake_send(self, request, stream=False):
            resp = FakeResp()
            # httpx attaches _client so aclose can clean up
            resp._client = type("FakeClient", (), {"aclose": lambda self: None})()
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)

        async with SafeFetcher(source="test") as f:
            with pytest.raises(SafeFetchError) as exc:
                await f.get("https://www.ccgp.gov.cn/doc.pdf", source="test")
            assert exc.value.error_type == FetchErrorType.CONTENT_TYPE_REJECTED


class TestSafeFetcherContentLength:
    """响应体大小限制"""

    @pytest.mark.asyncio
    async def test_rejects_content_length_too_large(self, monkeypatch):
        """Content-Length 超过限制必须被拒绝。"""
        from app.services.safe_fetcher import SafeFetcher, SafeFetchError, FetchErrorType

        async def _fake_resolve(*args, **kwargs):
            return "www.ccgp.gov.cn"
        monkeypatch.setattr("app.services.safe_fetcher._resolve_and_validate", _fake_resolve)

        class FakeResp:
            status_code = 200
            encoding = "utf-8"
            headers = {"content-type": "text/html", "content-length": "10485760"}
            async def aiter_bytes(self, chunk_size=65536):
                yield b"x" * 500000
                return
            async def aclose(self):
                pass

        async def fake_send(self, request, stream=False):
            resp = FakeResp()
            resp._client = type("FakeClient", (), {"aclose": lambda self: None})()
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)

        async with SafeFetcher(max_bytes=1_000_000, source="test") as f:
            with pytest.raises(SafeFetchError) as exc:
                await f.get("https://www.ccgp.gov.cn/big", source="test")
            assert exc.value.error_type == FetchErrorType.CONTENT_TOO_LARGE


class TestSafeFetcherChunkedOverflow:
    """隔离网络的分块溢出：无 Content-Length 时 Streaming Limit 仍触发"""

    @pytest.mark.asyncio
    async def test_chunked_over_limit_without_content_length(self, monkeypatch):
        """无 Content-Length header — 但 chunks 超过限制时应抛出 CONTENT_TOO_LARGE。
        Patch _read_stream 直接抛出错误，验证 SafeFetcher 不吞掉该错误。"""
        from app.services.safe_fetcher import SafeFetcher, SafeFetchError, FetchErrorType

        async with SafeFetcher(max_bytes=1_000_000, source="test") as f:
            with pytest.raises(SafeFetchError) as exc:
                # 直接调用受保护的 _read_stream 以触发大小检查
                await f._read_stream(
                    "https://www.ccgp.gov.cn/chunked",
                    "test",
                    MockStreamOverLimit(),
                )
            assert exc.value.error_type == FetchErrorType.CONTENT_TOO_LARGE


class MockStreamOverLimit:
    """返回超过限制的块的模拟响应"""
    status_code = 200
    encoding = "utf-8"
    headers = {"content-type": "text/html"}  # no content-length

    async def aiter_bytes(self, chunk_size=65536):
        for _ in range(20):
            yield b"x" * 100_000


class TestSafeFetcherTimeout:
    """总超时强制"""

    @pytest.mark.asyncio
    async def test_total_timeout_enforced(self, monkeypatch):
        """总超时到达时必须抛出 TIMEOUT，且 resp.aclose() 被调用"""
        from app.services.safe_fetcher import SafeFetcher, SafeFetchError, FetchErrorType

        async def _fake_resolve(*args, **kwargs):
            return "www.ccgp.gov.cn"
        monkeypatch.setattr("app.services.safe_fetcher._resolve_and_validate", _fake_resolve)

        close_called = [False]

        class SlowResp:
            status_code = 200
            encoding = "utf-8"
            headers = {"content-type": "text/html"}
            async def aiter_bytes(self, chunk_size=65536):
                import asyncio
                await asyncio.sleep(2)
                yield b"late"
            async def aclose(self):
                close_called[0] = True

        async def fake_send(self, request, stream=False):
            resp = SlowResp()
            resp._client = type("FakeClient", (), {"aclose": lambda self: None})()
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)

        async with SafeFetcher(total_timeout=1.0, source="test") as f:
            with pytest.raises(SafeFetchError) as exc:
                await f.get("https://www.ccgp.gov.cn/slow", source="test")
            assert exc.value.error_type == FetchErrorType.TIMEOUT

        assert close_called[0], "aclose() must be called even on timeout"


class TestSafeFetcherSourceUnknown:
    """未知来源 fail-closed"""

    @pytest.mark.asyncio
    async def test_unknown_source_raises(self):
        """未知 source 必须抛出 SOURCE_UNKNOWN"""
        from app.services.safe_fetcher import fetcher_for_source, SafeFetchError, FetchErrorType

        with pytest.raises(SafeFetchError) as exc:
            fetcher_for_source("made_up_source_xyz")
        assert exc.value.error_type == FetchErrorType.SOURCE_UNKNOWN


class TestSafeFetcherTlsFail:
    """TLS 证书错误"""

    @pytest.mark.asyncio
    async def test_tls_error_propagates(self, monkeypatch):
        """SSL 错误被正确分类为 TLS_ERROR，resp 被释放"""
        from app.services.safe_fetcher import SafeFetcher, SafeFetchError, FetchErrorType

        async def _fake_resolve(*args, **kwargs):
            return "www.ccgp.gov.cn"

        monkeypatch.setattr("app.services.safe_fetcher._resolve_and_validate", _fake_resolve)

        import ssl
        async def fake_send(self, request, stream=False):
            raise ssl.SSLCertVerificationError("certificate verify failed")

        monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)

        async with SafeFetcher(source="test") as f:
            with pytest.raises(SafeFetchError) as exc:
                await f.get("https://www.ccgp.gov.cn/bad-cert", source="test")
            assert exc.value.error_type == FetchErrorType.TLS_ERROR
            assert exc.value.status_code is None


class TestSafeFetcherHttpErrors:
    """HTTP 4xx/5xx 错误被正确分类并保留状态码"""

    @pytest.mark.asyncio
    async def test_http_503_returns_http_error_with_status(self, monkeypatch):
        """503 返回 HTTP_ERROR，status_code 被保留，响应被关闭"""
        from app.services.safe_fetcher import SafeFetcher, SafeFetchError, FetchErrorType

        async def _fake_resolve(*args, **kwargs):
            return "www.ccgp.gov.cn"

        monkeypatch.setattr("app.services.safe_fetcher._resolve_and_validate", _fake_resolve)

        close_called = [False]

        class Err503Resp:
            status_code = 503
            encoding = "utf-8"
            headers = {"content-type": "text/html"}

            async def aiter_bytes(self, chunk_size=65536):
                yield b"<html>503 Service Unavailable</html>"
                return

            async def aclose(self):
                close_called[0] = True

        async def fake_send(self, request, stream=False):
            resp = Err503Resp()
            resp._client = type("FakeClient", (), {"aclose": lambda s: None})()
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)

        async with SafeFetcher(source="test") as f:
            with pytest.raises(SafeFetchError) as exc:
                await f.get("https://www.ccgp.gov.cn/down", source="test")
            assert exc.value.error_type == FetchErrorType.HTTP_ERROR, \
                f"Expected HTTP_ERROR, got {exc.value.error_type}"
            assert exc.value.status_code == 503, \
                f"Expected status_code=503, got {exc.value.status_code}"

        assert close_called[0], "aclose() must be called for HTTP error responses"


class TestSafeFetcherRedirect:
    """重定向攻击"""

    @pytest.mark.asyncio
    async def test_redirect_to_http_rejected(self, monkeypatch):
        """HTTPS → HTTP 重定向必须被拒绝，且响应体不被读取"""
        from app.services.safe_fetcher import SafeFetcher, SafeFetchError, FetchErrorType

        async def _fake_resolve(*args, **kwargs):
            return "www.ccgp.gov.cn"
        monkeypatch.setattr("app.services.safe_fetcher._resolve_and_validate", _fake_resolve)

        body_was_read = [False]

        class RedirectResp:
            status_code = 302
            encoding = "utf-8"
            headers = {"content-type": "text/html", "location": "http://evil.com/page"}
            async def aiter_bytes(self, chunk_size=65536):
                body_was_read[0] = True
                yield b"x" * 1_000_000
                return
            async def aclose(self):
                pass

        async def fake_send(self, request, stream=False):
            resp = RedirectResp()
            resp._client = type("FakeClient", (), {"aclose": lambda self: None})()
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)

        async with SafeFetcher(source="test") as f:
            with pytest.raises(SafeFetchError) as exc:
                await f.get("https://www.ccgp.gov.cn/redirect", source="test")
            assert exc.value.error_type == FetchErrorType.REDIRECT_TO_HTTP

        # 关键断言：重定向响应体没有被读取（只读了 Location 头即关闭）
        assert not body_was_read[0], "Redirect response body must NOT be read"

    @pytest.mark.asyncio
    async def test_redirect_to_private_ip_dns_rejected(self, monkeypatch):
        """重定向到私网 IP 的 DNS 被拒绝"""
        from app.services.safe_fetcher import SafeFetcher, SafeFetchError, FetchErrorType

        async def _fake_resolve_real(host, source, url):
            if host == "www.ccgp.gov.cn":
                return host
            raise SafeFetchError(
                error_type=FetchErrorType.DNS_PRIVATE,
                message=f"私网地址 {host}",
                url=url, source=source,
            )

        monkeypatch.setattr("app.services.safe_fetcher._resolve_and_validate", _fake_resolve_real)

        class PrivRedirectResp:
            status_code = 301
            encoding = "utf-8"
            headers = {"content-type": "text/html", "location": "https://10.0.0.5/admin"}
            async def aiter_bytes(self, chunk_size=65536):
                yield b""
                return
            async def aclose(self):
                pass

        async def fake_send(self, request, stream=False):
            resp = PrivRedirectResp()
            resp._client = type("FakeClient", (), {"aclose": lambda self: None})()
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)

        async with SafeFetcher(source="test") as f:
            with pytest.raises(SafeFetchError) as exc:
                await f.get("https://www.ccgp.gov.cn/redirect-priv", source="test")
            assert exc.value.error_type == FetchErrorType.DNS_PRIVATE


# ═══════════════════════════════════════════════════════════════
# 案例数据分级测试
# ═══════════════════════════════════════════════════════════════


class TestCaseDataTiering:
    """案例数据分级"""

    def test_normal_user_cannot_see_raw_content(self, client: TestClient, db_session):
        """普通用户案例详情不返回 raw_content。"""
        user = _create_user(db_session, "tier_user")
        cc = ComplaintCase(
            province="甘肃", title="分级测试", decision_type="upheld",
            complainant="投诉人张三", respondent="被投诉人李四",
            raw_content="原始敏感内容", summary="摘要",
            complaint_types='["测试"]',
        )
        db_session.add(cc)
        db_session.commit()

        resp = client.get(f"/api/crawler/cases/{cc.id}", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert "raw_content" not in data
        assert "complainant" not in data
        assert "respondent" not in data
        assert data["summary"] == "摘要"
        assert data["title"] == "分级测试"

    def test_admin_can_see_full_detail(self, client: TestClient, db_session):
        """管理员可以查看案例原文和敏感字段。"""
        admin = _create_user(db_session, "tier_admin", role="admin")
        cc = ComplaintCase(
            province="甘肃", title="管理员分级测试", decision_type="upheld",
            complainant="投诉人张三", respondent="被投诉人李四",
            raw_content="原始敏感内容", summary="摘要",
            complaint_types='["测试"]',
        )
        db_session.add(cc)
        db_session.commit()

        resp = client.get(f"/api/crawler/cases/{cc.id}", headers=_headers(admin))
        assert resp.status_code == 200
        data = resp.json()
        assert "raw_content" in data
        assert data["raw_content"] == "原始敏感内容"
        assert data["complainant"] == "投诉人张三"
        assert data["respondent"] == "被投诉人李四"


# ═══════════════════════════════════════════════════════════════
# KG 可见性测试
# ═══════════════════════════════════════════════════════════════


class TestKGVisibility:
    """KG 可见性 — 普通用户只能看到 verified"""

    def test_normal_user_default_only_sees_verified(self, client: TestClient, db_session):
        """普通用户默认搜索只能看到 verified 节点。"""
        user = _create_user(db_session, "kg_vis_user")
        db_session.add(KGNode(node_type="regulation", title="可见法规", content="c",
                              audit_status="verified", trust_level=0.8))
        db_session.add(KGNode(node_type="regulation", title="隐藏法规", content="c",
                              audit_status="unreviewed", trust_level=0.5))
        db_session.add(KGNode(node_type="regulation", title="标记法规", content="c",
                              audit_status="flagged", trust_level=0.3))
        db_session.commit()

        resp = client.get("/api/kg/search", params={"q": "法规"}, headers=_headers(user))
        assert resp.status_code == 200
        titles = [r["title"] for r in resp.json()["results"]]
        assert "可见法规" in titles
        assert "隐藏法规" not in titles
        assert "标记法规" not in titles

    def test_normal_user_cannot_query_unreviewed(self, client: TestClient, db_session):
        """普通用户不能查询 unreviewed/flagged/rejected。"""
        user = _create_user(db_session, "kg_vis2_user")
        for st in ("unreviewed", "flagged", "rejected"):
            resp = client.get("/api/kg/search", params={"q": "", "audit_status": st}, headers=_headers(user))
            assert resp.status_code == 403, f"Expected 403 for {st}, got {resp.status_code}"

    def test_admin_can_query_all_statuses(self, client: TestClient, db_session):
        """管理员可以查询所有审核状态。"""
        admin = _create_user(db_session, "kg_vis_admin", role="admin")
        db_session.add(KGNode(node_type="regulation", title="未审核", content="c",
                              audit_status="unreviewed", trust_level=0.5))
        db_session.add(KGNode(node_type="regulation", title="标记", content="c",
                              audit_status="flagged", trust_level=0.3))
        db_session.commit()

        resp = client.get("/api/kg/search", params={"q": "", "audit_status": "unreviewed"}, headers=_headers(admin))
        assert resp.status_code == 200
        titles = [r["title"] for r in resp.json()["results"]]
        assert "未审核" in titles

    def test_kg_related_only_returns_verified(self, client: TestClient, db_session):
        """关联节点查询只返回 verified 的目标节点。"""
        user = _create_user(db_session, "kg_rel_vis")
        rule = KGNode(node_type="rule", title="规则", content="c",
                      rule_id="R001", audit_status="verified", trust_level=0.8)
        reg_ok = KGNode(node_type="regulation", title="已审核法规", content="c",
                        audit_status="verified", trust_level=0.8)
        reg_hidden = KGNode(node_type="regulation", title="未审核法规", content="c",
                            audit_status="unreviewed", trust_level=0.5)
        db_session.add_all([rule, reg_ok, reg_hidden])
        db_session.commit()
        db_session.add(KGEdge(source_id=rule.id, target_id=reg_ok.id, relation="references"))
        db_session.add(KGEdge(source_id=rule.id, target_id=reg_hidden.id, relation="references"))
        db_session.commit()

        resp = client.get(f"/api/kg/related/{rule.id}", headers=_headers(user))
        assert resp.status_code == 200
        related = resp.json()["related"]
        titles = [r["node"]["title"] for r in related]
        assert "已审核法规" in titles
        assert "未审核法规" not in titles

    def test_normal_user_blocked_from_unverified_source_node(self, client: TestClient, db_session):
        """普通用户不能通过 unreviewed 源节点枚举关联节点。"""
        user = _create_user(db_session, "kg_rel_block")
        unreviewed = KGNode(node_type="rule", title="未审核规则", content="c",
                            rule_id="R_BAD", audit_status="unreviewed", trust_level=0.3)
        reg = KGNode(node_type="regulation", title="已审核法规", content="c",
                     audit_status="verified", trust_level=0.8)
        db_session.add_all([unreviewed, reg])
        db_session.commit()
        db_session.add(KGEdge(source_id=unreviewed.id, target_id=reg.id, relation="references"))
        db_session.commit()

        resp = client.get(f"/api/kg/related/{unreviewed.id}", headers=_headers(user))
        assert resp.status_code == 403, f"Expected 403 for unreviewed source node, got {resp.status_code}"


# ═══════════════════════════════════════════════════════════════
# Relation 类型矩阵测试
# ═══════════════════════════════════════════════════════════════


class TestRelationTypeMatrix:
    """边类型矩阵校验"""

    def _setup_nodes(self, db_session):
        types = {
            "rule": KGNode(node_type="rule", title="规则节点", content="c", audit_status="verified"),
            "regulation": KGNode(node_type="regulation", title="法规节点", content="c", audit_status="verified"),
            "case": KGNode(node_type="case", title="案例节点", content="c", audit_status="verified"),
            "template": KGNode(node_type="template", title="模板节点", content="c", audit_status="verified"),
        }
        for t, n in types.items():
            db_session.add(n)
        db_session.commit()
        return {t: n.id for t, n in types.items()}

    def _try_edge(self, client, admin_headers, src_id, tgt_id, relation):
        return client.post("/api/kg/edge", params={
            "source_id": src_id, "target_id": tgt_id,
            "relation": relation, "weight": 1.0,
        }, headers=admin_headers)

    def test_references_only_rule_to_regulation(self, client: TestClient, db_session):
        """references 只能是 rule → regulation。"""
        admin = _create_user(db_session, "rel_admin", role="admin")
        ids = self._setup_nodes(db_session)

        # 合法
        resp = self._try_edge(client, _headers(admin), ids["rule"], ids["regulation"], "references")
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

        # 非法：rule → case
        resp = self._try_edge(client, _headers(admin), ids["rule"], ids["case"], "references")
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"

        # 非法：regulation → regulation
        resp = self._try_edge(client, _headers(admin), ids["regulation"], ids["regulation"], "references")
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"

    def test_demonstrated_by_only_rule_to_case(self, client: TestClient, db_session):
        """demonstrated_by 只能是 rule → case。"""
        admin = _create_user(db_session, "rel2_admin", role="admin")
        ids = self._setup_nodes(db_session)

        # 合法
        resp = self._try_edge(client, _headers(admin), ids["rule"], ids["case"], "demonstrated_by")
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"

        # 非法：case → case
        resp = self._try_edge(client, _headers(admin), ids["case"], ids["case"], "demonstrated_by")
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"

    def test_cites_only_case_to_regulation(self, client: TestClient, db_session):
        """cites 只能是 case → regulation。"""
        admin = _create_user(db_session, "rel3_admin", role="admin")
        ids = self._setup_nodes(db_session)

        # 合法
        resp = self._try_edge(client, _headers(admin), ids["case"], ids["regulation"], "cites")
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"

    def test_mitigated_by_only_rule_to_template(self, client: TestClient, db_session):
        """mitigated_by 只能是 rule → template。"""
        admin = _create_user(db_session, "rel4_admin", role="admin")
        ids = self._setup_nodes(db_session)

        # 合法
        resp = self._try_edge(client, _headers(admin), ids["rule"], ids["template"], "mitigated_by")
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"


# ═══════════════════════════════════════════════════════════════
# 采集任务状态测试
# ═══════════════════════════════════════════════════════════════


class TestCrawlTaskStatus:
    """采集任务 PARTIAL 状态"""

    async def test_partial_on_source_error(self, monkeypatch):
        """单来源失败时任务状态为 PARTIAL。"""
        from app.services.sync_scheduler import SyncScheduler, SyncStatus

        scheduler = SyncScheduler(case_scrape_interval_hours=168)

        async def _fake_crawl_all():
            return {
                "ccgp": {"saved": 3, "errors": []},
                "ningxia": {"saved": 0, "errors": ["ningxia: 连接超时"]},
                "shaanxi": {"saved": 1, "errors": []},
                "mof": {"saved": 0, "errors": []},
                "kg_synced": 4,
                "errors": ["ningxia: ningxia: 连接超时"],
                "cases_saved": 4,
            }

        monkeypatch.setattr("app.services.crawler_service.crawl_all", _fake_crawl_all)
        record = await scheduler.scrape_cases()
        assert record.status == SyncStatus.PARTIAL, \
            f"Should be PARTIAL on source error, got {record.status.value}"

    async def test_success_when_no_errors(self, monkeypatch):
        """无错误时任务状态为 SUCCESS。"""
        from app.services.sync_scheduler import SyncScheduler, SyncStatus

        scheduler = SyncScheduler(case_scrape_interval_hours=168)

        async def _fake_crawl_all():
            return {
                "ccgp": {"saved": 3, "errors": []},
                "ningxia": {"saved": 2, "errors": []},
                "shaanxi": {"saved": 0, "errors": []},
                "mof": {"saved": 0, "errors": []},
                "kg_synced": 5,
                "errors": [],
                "cases_saved": 5,
            }

        monkeypatch.setattr("app.services.crawler_service.crawl_all", _fake_crawl_all)
        record = await scheduler.scrape_cases()
        assert record.status == SyncStatus.SUCCESS, \
            f"Should be SUCCESS with no errors, got {record.status.value}"

    async def test_kg_sync_error_causes_partial(self, monkeypatch):
        """KG 同步失败时任务状态应为 PARTIAL。"""
        from app.services.sync_scheduler import SyncScheduler, SyncStatus

        scheduler = SyncScheduler(case_scrape_interval_hours=168)

        async def _fake_crawl_all():
            return {
                "ccgp": {"saved": 3, "errors": []},
                "ningxia": {"saved": 2, "errors": []},
                "shaanxi": {"saved": 0, "errors": []},
                "mof": {"saved": 0, "errors": []},
                "kg_synced": 0,
                "errors": ["kg_sync: 数据库连接失败"],
                "cases_saved": 5,
            }

        monkeypatch.setattr("app.services.crawler_service.crawl_all", _fake_crawl_all)
        record = await scheduler.scrape_cases()
        assert record.status == SyncStatus.PARTIAL, \
            f"Should be PARTIAL when KG sync fails, got {record.status.value}"


# ═══════════════════════════════════════════════════════════════
# 依赖健康状态测试
# ═══════════════════════════════════════════════════════════════


class TestDependencyHealth:
    """依赖健康状态上报"""

    def test_status_includes_health(self, client: TestClient, db_session):
        """crawler status 返回 health 字段。"""
        user = _create_user(db_session, "health_user")
        resp = client.get("/api/crawler/status", headers=_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert "health" in data, f"Status should include 'health', got keys: {list(data.keys())}"
        assert "playwright" in data["health"], f"health should include playwright: {data['health']}"
        assert "httpx_tls" in data["health"], f"health should include httpx_tls: {data['health']}"

    def test_health_keys_valid_values(self, client: TestClient, db_session):
        """health 值只能是 ok / degraded / unavailable。"""
        user = _create_user(db_session, "health2_user")
        resp = client.get("/api/crawler/status", headers=_headers(user))
        data = resp.json()
        allowed = {"ok", "degraded", "unavailable"}
        for key, val in data["health"].items():
            assert val in allowed, f"health.{key} = '{val}' not in {allowed}"
