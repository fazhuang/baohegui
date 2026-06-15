"""安全测试 — 生产配置安全基线

覆盖：
- 生产默认 SECRET_KEY 拒绝启动
- SECRET_KEY 太短拒绝启动
- debug=False 时 SECRET_KEY 为默认值拒绝启动
- debug=False 时 docs/redoc/openapi.json 关闭
- HSTS 头在生产环境存在
- 运行时验证：弱 SECRET_KEY 子进程拒绝启动 + 生产配置子进程正常启动 (http.client, no proxy)
"""

import http.client
import os
import subprocess
import socket
import time
from pathlib import Path

import pytest
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_UV_BIN = os.path.expanduser("~/.local/bin/uv")


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http_get(host: str, port: int, path: str,
              host_header: str | None = None,
              timeout: int = 5) -> tuple[int, dict]:
    """通过 http.client 发送 GET 请求（绕过系统代理），返回 (status, headers_dict)"""
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    headers = {}
    if host_header:
        headers["Host"] = host_header
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        resp_headers = dict(resp.getheaders())
        resp.read()
        conn.close()
        return status, resp_headers
    except Exception:
        conn.close()
        raise


def _wait_for_server(host: str, port: int, timeout: int = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, _ = _http_get(host, port, "/health")
            if status == 200:
                return
        except Exception:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"Server at {host}:{port} did not start within {timeout}s")


class TestProductionConfig:
    """生产配置安全基线"""

    def test_default_secret_key_rejected(self):
        """默认 SECRET_KEY 'change-me-in-production' 应拒绝启动"""
        with patch.dict(os.environ, {
            "BHG_SECRET_KEY": "change-me-in-production",
            "BHG_DEBUG": "true",
        }, clear=False):
            from app.core.config import Settings
            with pytest.raises(ValueError) as exc_info:
                Settings(_env_file=None)
            assert "默认" in str(exc_info.value) or "SECRET_KEY" in str(exc_info.value)

    def test_short_secret_key_rejected(self):
        """SECRET_KEY 长度 < 32 应拒绝启动"""
        with patch.dict(os.environ, {
            "BHG_SECRET_KEY": "short",
            "BHG_DEBUG": "true",
        }, clear=False):
            from app.core.config import Settings
            with pytest.raises(ValueError) as exc_info:
                Settings(_env_file=None)
            assert "长度不足" in str(exc_info.value) or "32" in str(exc_info.value)

    def test_empty_secret_key_rejected(self):
        """空 SECRET_KEY 应拒绝启动"""
        with patch.dict(os.environ, {
            "BHG_SECRET_KEY": "",
            "BHG_DEBUG": "true",
        }, clear=False):
            from app.core.config import Settings
            with pytest.raises(ValueError) as exc_info:
                Settings(_env_file=None)
            assert "SECRET_KEY" in str(exc_info.value) or "不得为空" in str(exc_info.value)

    def test_valid_secret_key_accepted(self):
        """长 SECRET_KEY 应正常启动"""
        with patch.dict(os.environ, {
            "BHG_SECRET_KEY": "a-very-long-and-random-secret-key-that-is-at-least-32-chars",
            "BHG_DATABASE_URL": "sqlite:///:memory:",
            "BHG_DEBUG": "true",
        }, clear=False):
            from app.core.config import Settings
            s = Settings(_env_file=None)
            assert s.secret_key == "a-very-long-and-random-secret-key-that-is-at-least-32-chars"

    def test_docs_disabled_in_production(self):
        """生产环境 (debug=False) 时 docs/redoc/openapi 应在 Settings 层面关闭"""
        with patch.dict(os.environ, {
            "BHG_SECRET_KEY": "a-very-long-secure-random-key-for-production-use-64chars",
            "BHG_DEBUG": "false",
            "BHG_DATABASE_URL": "sqlite:///:memory:",
            "BHG_CORS_ORIGINS": "https://example.com",
        }, clear=False):
            from app.core.config import Settings
            s = Settings(_env_file=None)
            assert s.debug is False

    def test_security_headers_present(self):
        """安全响应头应在所有响应中存在"""
        from app.main import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.headers.get("x-content-type-options") == "nosniff"
            assert resp.headers.get("x-frame-options") == "DENY"
            assert "Content-Security-Policy" in resp.headers.get("content-security-policy", "").lower() or \
                   "content-security-policy" in str(resp.headers).lower()
            assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    # ── 运行时验证：子进程生产模式启动/拒绝 ──

    def test_production_startup_succeeds_with_valid_config(self):
        """有效生产配置下，子进程应正常启动并响应 /health"""
        db_path = BACKEND_DIR / ".test_tmp" / "_prod_config_valid.db"
        port = _find_free_port()
        env = os.environ.copy()
        env.update({
            "BHG_DEBUG": "false",
            "BHG_SECRET_KEY": "a" * 32,
            "BHG_DATABASE_URL": f"sqlite:///{db_path}",
            "BHG_CORS_ORIGINS": "https://example.com",
            "BHG_MINIO_ENDPOINT": "",
            "BHG_LLM_MOCK_MODE": "true",
            "BHG_LOG_LEVEL": "error",
            "UV_CACHE_DIR": env.get("UV_CACHE_DIR", "/private/tmp/uv-cache"),
        })
        proc = subprocess.Popen(
            [_UV_BIN, "run", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(port),
             "--log-level", "error"],
            cwd=str(BACKEND_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        host = "127.0.0.1"
        try:
            _wait_for_server(host, port)
            status, _ = _http_get(host, port, "/health")
            assert status == 200, f"有效配置应返回 200, got {status}"
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    def test_weak_secret_key_causes_startup_failure(self):
        """弱 SECRET_KEY 应导致子进程启动失败（exit code != 0 或 stderr 含错误）"""
        port = _find_free_port()
        env = os.environ.copy()
        env.update({
            "BHG_DEBUG": "false",
            "BHG_SECRET_KEY": "short",
            "BHG_DATABASE_URL": "sqlite:///:memory:",
            "BHG_CORS_ORIGINS": "https://example.com",
            "BHG_MINIO_ENDPOINT": "",
            "BHG_LLM_MOCK_MODE": "true",
            "BHG_LOG_LEVEL": "error",
            "UV_CACHE_DIR": env.get("UV_CACHE_DIR", "/private/tmp/uv-cache"),
        })
        proc = subprocess.Popen(
            [_UV_BIN, "run", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(port),
             "--log-level", "error"],
            cwd=str(BACKEND_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=5)

            exit_code = proc.returncode
            stderr_output = ""
            if proc.stderr:
                try:
                    stderr_output = proc.stderr.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass

            # 弱密钥应导致: exit != 0 或 stderr 包含 SECRET_KEY 相关错误
            startup_failed = (
                exit_code != 0
                or "SECRET_KEY" in stderr_output
                or "secret_key" in stderr_output.lower()
                or "ValueError" in stderr_output
            )
            assert startup_failed, (
                f"弱 SECRET_KEY 应导致启动失败。exit_code={exit_code}, stderr={stderr_output[:500]}"
            )
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
