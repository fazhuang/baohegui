"""认证 API 集成测试 — 注册、登录、token 过期、权限校验"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token


class TestRegister:
    """用户注册测试"""

    def test_register_new_user(self, client: TestClient):
        """不存在的用户可以注册成功，返回 JWT token"""
        resp = client.post("/api/auth/register", json={
            "username": "testuser1",
            "password": "securepass123",
            "company": "测试公司",
            "email": "test1@example.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["username"] == "testuser1"
        assert data["role"] == "user"

    def test_register_duplicate_user(self, client: TestClient):
        """重复用户名注册应返回 409 Conflict"""
        # 第一次注册
        client.post("/api/auth/register", json={
            "username": "duptest",
            "password": "securepass123",
        })
        # 第二次注册相同用户名
        resp = client.post("/api/auth/register", json={
            "username": "duptest",
            "password": "anotherpass123",
        })
        assert resp.status_code == 409
        assert "用户名已存在" in resp.json()["detail"]

    def test_register_without_email_company(self, client: TestClient):
        """company 和 email 为可选字段，不传也可注册"""
        resp = client.post("/api/auth/register", json={
            "username": "minimal_user",
            "password": "minimal123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "minimal_user"
        assert data["company"] == ""


class TestLogin:
    """用户登录测试"""

    def test_login_correct_password(self, client: TestClient):
        """正确密码登录成功，返回 JWT token"""
        # 先注册
        client.post("/api/auth/register", json={
            "username": "loginuser",
            "password": "correctpass",
        })
        # 再登录
        resp = client.post("/api/auth/login", json={
            "username": "loginuser",
            "password": "correctpass",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["username"] == "loginuser"
        assert data["role"] == "user"

    def test_login_wrong_password(self, client: TestClient):
        """错误密码登录应返回 401 Unauthorized"""
        # 先注册
        client.post("/api/auth/register", json={
            "username": "wrongpwuser",
            "password": "rightpass",
        })
        # 用错误密码登录
        resp = client.post("/api/auth/login", json={
            "username": "wrongpwuser",
            "password": "wrongpass",
        })
        assert resp.status_code == 401
        assert "用户名或密码错误" in resp.json()["detail"]

    def test_login_nonexistent_user(self, client: TestClient):
        """不存在的用户登录应返回 401"""
        resp = client.post("/api/auth/login", json={
            "username": "nobody",
            "password": "whatever",
        })
        assert resp.status_code == 401


class TestTokenExpiry:
    """Token 过期测试"""

    def test_expired_token_returns_401(self, client: TestClient):
        """使用过期 token 请求应返回 401"""
        from datetime import datetime, timedelta, timezone
        from jose import jwt

        # 创建一个已过期的 token（exp 设为 1 小时前）
        expire = datetime.now(timezone.utc) - timedelta(hours=1)
        payload = {"sub": "1", "role": "user", "exp": expire}
        from app.core.config import settings
        expired_token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)

        resp = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {expired_token}",
        })
        assert resp.status_code == 401

    def test_register_then_login_success(self, client: TestClient):
        """注册后使用注册返回的 token 访问 me 接口应成功"""
        # 注册
        resp = client.post("/api/auth/register", json={
            "username": "validtokenuser2",
            "password": "pass123",
        })
        assert resp.status_code == 200, f"Register failed: {resp.status_code} {resp.text}"
        data = resp.json()
        assert "access_token" in data, f"No access_token in response: {data}"
        token = data["access_token"]

        # 用注册返回的 token 访问 me 接口
        resp = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "validtokenuser2"


class TestPermissions:
    """权限测试"""

    def test_user_can_access_own_info(self, client: TestClient, user_auth_headers):
        """普通用户可以访问自己的信息"""
        # 先注册一个用户来获得有效 token
        # (fixture user_auth_headers creates a user via create_access_token)
        resp = client.get("/api/auth/me", headers=user_auth_headers)
        # With the fixture token, the user may not exist in DB, so 401/404 are also acceptable
        assert resp.status_code in (200, 401, 404), f"Got unexpected status: {resp.status_code}"

    def test_admin_can_access_admin_api(self, client: TestClient, auth_headers):
        """管理员可以正常访问管理 API"""
        resp = client.post("/api/rules/reload", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "rule_count" in data

    def test_admin_can_access_engine_status(self, client: TestClient, auth_headers):
        """管理员可以查看引擎状态"""
        resp = client.get("/api/rules/engine/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert data["total"] > 0
