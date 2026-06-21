"""安全测试 — FastAPI 安全基线与代码级安全

覆盖：
- 安全响应头存在（TestClient + 子进程生产模式双重验证）
- 非 debug 模式下 docs/redoc/openapi.json 返回 404/403（子进程运行时验证）
- 非法 Host 头被拒绝（子进程运行时验证）
- 开发模式 fallback 登录已移除
- auth.py 不包含默认账号创建函数
- frontend build 不包含 dev-token / admin123 / 开发模式 / 一键登录 / saved_password
"""

import http.client
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
# uv 全路径（优先 PATH 查找，回退到 ~/.local/bin/uv）
_UV_BIN = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")


def _find_free_port() -> int:
    """找到一个空闲的 TCP 端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http_get(host: str, port: int, path: str,
              host_header: str | None = None,
              timeout: int = 5) -> tuple[int, dict]:
    """通过 http.client 发送 GET 请求（绕过系统代理），返回 (status, headers_dict)。

    连接错误时返回 (-1, {})，不在调用方到处 try/except。
    """
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    headers = {}
    if host_header:
        headers["Host"] = host_header
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        resp_headers = dict(resp.getheaders())
        resp.read()  # consume body
        conn.close()
        return status, resp_headers
    except Exception:
        conn.close()
        return -1, {}


def _wait_for_server(host: str, port: int, proc: subprocess.Popen | None = None,
                    timeout: int = 30) -> None:
    """轮询等待服务器就绪。

    第一次探测前等待 2s 给 uvicorn 导入时间。
    如果提供了 proc，在每次轮询时检查进程是否存活，
    若进程已退出，立即抛出 RuntimeError 并附带 stderr。
    """
    time.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            _, stderr = _kill_server(proc)
            raise RuntimeError(
                f"Server process exited with code {proc.returncode} before port {port} became ready.\n"
                f"stderr: {stderr[-2000:]}"
            )
        try:
            status, _ = _http_get(host, port, "/health", timeout=3)
            if status == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Server at {host}:{port} did not start within {timeout}s")


def _start_prod_server(port: int, extra_env: dict | None = None) -> subprocess.Popen:
    """启动生产模式子进程服务器（通过 uv run 确保依赖环境一致）。

    Raises RuntimeError if uv binary is not found.
    """
    if not os.path.isfile(_UV_BIN):
        raise RuntimeError(
            f"uv not found at {_UV_BIN}. Install uv or set PATH to include uv."
        )

    db_path = BACKEND_DIR / ".test_tmp" / f"_prod_sec_{port}.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update({
        "BHG_DEBUG": "false",
        "BHG_SECRET_KEY": "a-very-long-and-random-secret-key-for-production-use-64chars",
        "BHG_DATABASE_URL": f"sqlite:///{db_path}",
        "BHG_CORS_ORIGINS": "https://example.com",
        "BHG_MINIO_ENDPOINT": "",  # 本地存储模式
        "BHG_LLM_MOCK_MODE": "true",
        "BHG_LOG_LEVEL": "error",
        "UV_CACHE_DIR": env.get("UV_CACHE_DIR", os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache/uv"))),
    })
    if extra_env:
        env.update(extra_env)

    return subprocess.Popen(
        [
            _UV_BIN, "run", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(port),
            "--log-level", "error",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _kill_server(proc: subprocess.Popen) -> tuple[str, str]:
    """优雅终止服务器子进程，返回捕获的 stdout/stderr 用于诊断。"""
    try:
        proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        return (
            stdout.decode(errors="replace") if stdout else "",
            stderr.decode(errors="replace") if stderr else "",
        )
    except ProcessLookupError:
        return "", ""
    except Exception:
        return "", ""


class TestFastAPISecurityBaseline:
    """FastAPI 安全基线"""

    # ── TestClient-based 测试（debug 模式下验证） ──

    def test_security_headers_present(self):
        """安全响应头应在 /health 响应中存在"""
        from app.main import app

        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.headers.get("x-content-type-options") == "nosniff"
            assert resp.headers.get("x-frame-options") == "DENY"
            assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
            csp = resp.headers.get("content-security-policy", "")
            assert "default-src" in csp
            assert "frame-ancestors 'none'" in csp

    def test_no_default_admin_in_auth_module(self):
        """auth.py 不应包含 _ensure_default_admin 函数（已被移除）"""
        from app.api import auth
        assert not hasattr(auth, "_ensure_default_admin"), (
            "auth.py 中不应存在 _ensure_default_admin 函数，默认账号创建已移除"
        )

    def test_no_dev_token_in_frontend_build(self):
        """前端构建产物中不应包含 dev-token、开发模式、一键登录、admin123、user123、saved_password"""
        dist_paths = [
            Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist",
        ]
        dist_dir = None
        for p in dist_paths:
            if p.exists():
                dist_dir = p
                break

        if not dist_dir:
            pytest.skip("前端 dist 目录不存在，跳过构建产物检查。运行 npm run build 生成。")

        try:
            result = subprocess.run(
                ["grep", "-R", "-o", "-E",
                 "dev-token|开发模式|一键登录|admin123|user123|saved_password"],
                cwd=str(dist_dir),
                capture_output=True,
                text=True,
            )
            matches = result.stdout.strip()
            if matches:
                pytest.fail(f"前端构建产物包含禁用关键词:\n{matches}")
        except FileNotFoundError:
            pytest.skip("grep 命令不可用")

    def test_auth_login_no_fallback(self):
        """login API 不应有硬编码 fallback 登录（admin/admin123, user/user123）"""
        import inspect
        from app.api.auth import login

        source = inspect.getsource(login)
        assert "admin123" not in source, "login 函数中不应包含硬编码密码 admin123"
        assert "user123" not in source, "login 函数中不应包含硬编码密码 user123"
        assert "_ensure_default_admin" not in source, "login 函数中不应调用 _ensure_default_admin"

    # ── 子进程生产模式运行时测试 ──

    def test_production_docs_disabled(self):
        """生产模式 (debug=false) 下 /docs, /redoc, /openapi.json 应返回 404 或 403（不能是 200）"""
        port = _find_free_port()
        proc = _start_prod_server(port)
        host = "127.0.0.1"
        try:
            _wait_for_server(host, port, proc=proc)

            # /docs
            status, _ = _http_get(host, port, "/docs")
            assert status not in (200,), (
                f"生产模式 /docs 不应返回 200, got {status}"
            )
            assert status in (404, 403), (
                f"生产模式 /docs 应返回 404 或 403, got {status}"
            )

            # /redoc
            status, _ = _http_get(host, port, "/redoc")
            assert status not in (200,), (
                f"生产模式 /redoc 不应返回 200, got {status}"
            )
            assert status in (404, 403), (
                f"生产模式 /redoc 应返回 404 或 403, got {status}"
            )

            # /openapi.json
            status, _ = _http_get(host, port, "/openapi.json")
            assert status not in (200,), (
                f"生产模式 /openapi.json 不应返回 200, got {status}"
            )
            assert status in (404, 403), (
                f"生产模式 /openapi.json 应返回 404 或 403, got {status}"
            )
        finally:
            _kill_server(proc)

    def test_production_illegal_host_rejected(self):
        """非法 Host 头在生产模式应被拒绝（不能返回 200），合法 Host 应通过"""
        port = _find_free_port()
        proc = _start_prod_server(port)
        host = "127.0.0.1"
        try:
            _wait_for_server(host, port, proc=proc)

            # 合法 Host: localhost → 200
            status, _ = _http_get(host, port, "/health", host_header="localhost")
            assert status == 200, f"合法 Host localhost 应返回 200, got {status}"

            # 合法 Host: 127.0.0.1:{port} → 200
            status, _ = _http_get(host, port, "/health", host_header=f"127.0.0.1:{port}")
            assert status == 200, f"合法 Host 127.0.0.1 应返回 200, got {status}"

            # 非法 Host: evil.example → 400/403/421（不能是 200）
            status, _ = _http_get(host, port, "/health", host_header="evil.example")
            assert status not in (200,), (
                f"非法 Host evil.example 不应返回 200, got {status}"
            )
            assert status in (400, 403, 404, 421), (
                f"非法 Host 应返回 400/403/404/421, got {status}"
            )
        finally:
            _kill_server(proc)

    def test_production_security_headers(self):
        """生产模式 /health 响应必须包含完整安全响应头"""
        port = _find_free_port()
        proc = _start_prod_server(port)
        host = "127.0.0.1"
        try:
            _wait_for_server(host, port, proc=proc)

            status, headers = _http_get(host, port, "/health")
            assert status == 200

            # 所有安全头必须存在
            assert "x-content-type-options" in headers, "缺少 X-Content-Type-Options"
            assert "x-frame-options" in headers, "缺少 X-Frame-Options"
            assert "referrer-policy" in headers, "缺少 Referrer-Policy"

            # Content-Security-Policy — 大小写不敏感
            csp = headers.get("content-security-policy", "")
            assert csp, "缺少 Content-Security-Policy 头"
            assert "frame-ancestors 'none'" in csp, (
                f"CSP 缺少 frame-ancestors 'none': {csp}"
            )

            # HSTS: 生产模式 (debug=false) 必须存在
            hsts = headers.get("strict-transport-security", "")
            assert hsts, "生产模式缺少 Strict-Transport-Security (HSTS) 头"
            assert "max-age=" in hsts, f"HSTS 格式不正确: {hsts}"
        finally:
            _kill_server(proc)
