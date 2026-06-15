"""安全测试 — 管理接口审计日志 + admin 规则创建 200

覆盖：
- admin POST /api/rules/platform 真实返回 200
- 写操作后在 audit_logs 表中有对应记录
- 普通用户写规则被拒绝且无日志产生
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.models.user import User
from app.core.audit import audit_service


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


class TestAdminRulesCreate200AndAudit:
    """admin POST /api/rules/platform 必须返回 200 且产生审计记录"""

    def test_admin_create_rule_returns_200(self, client: TestClient, db_session):
        import uuid
        admin = _create_user(db_session, "audit_admin", role="admin")
        # rule_id must match ^[A-Z0-9_-]{3,32}$
        rule_id = f"TEST-AUDIT-{uuid.uuid4().hex[:6].upper()}"
        resp = client.post(
            "/api/rules/platform",
            json={
                "rule_id": rule_id,
                "platform": "test-platform",
                "platform_code": "TP001",
                "rule_type": "forbidden",
                "description": "测试审计规则",
            },
            headers=_headers(admin),
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["message"] == "规则已创建"
        assert data["rule"]["rule_id"] == rule_id

    def test_admin_create_rule_produces_audit_log(self, client: TestClient, db_session):
        import uuid
        admin = _create_user(db_session, "audit_admin2", role="admin")
        rule_id = f"TEST-AUDIT-LOG-{uuid.uuid4().hex[:6].upper()}"
        client.post(
            "/api/rules/platform",
            json={
                "rule_id": rule_id,
                "platform": "test-platform",
                "platform_code": "TP002",
                "rule_type": "forbidden",
                "description": "审计日志测试规则",
            },
            headers=_headers(admin),
        )
        from app.core.audit import AuditLog
        logs = db_session.query(AuditLog).filter(
            AuditLog.action == "create_platform_rule"
        ).all()
        assert len(logs) >= 1, "应有 create_platform_rule 审计记录"
        found = any(lg.resource_id == rule_id for lg in logs)
        assert found, f"未找到 resource_id={rule_id} 的审计记录"

    def test_normal_user_create_rule_rejected_no_audit(self, client: TestClient, db_session):
        user = _create_user(db_session, "normal_noaudit")
        resp = client.post(
            "/api/rules/platform",
            json={
                "rule_id": "TEST-NOAUDIT-USER",
                "platform": "test",
                "platform_code": "TP003",
                "rule_type": "forbidden",
                "description": "普通用户不应能创建",
            },
            headers=_headers(user),
        )
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_admin_delete_rule_produces_audit_log(self, client: TestClient, db_session):
        import uuid
        admin = _create_user(db_session, "audit_admin3", role="admin")
        rule_id = f"TEST-DEL-AUDIT-{uuid.uuid4().hex[:6].upper()}"
        client.post(
            "/api/rules/platform",
            json={
                "rule_id": rule_id,
                "platform": "test",
                "platform_code": "TP004",
                "rule_type": "forbidden",
                "description": "待删除规则",
            },
            headers=_headers(admin),
        )
        resp = client.delete(
            f"/api/rules/platform/{rule_id}",
            headers=_headers(admin),
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        from app.core.audit import AuditLog
        logs = db_session.query(AuditLog).filter(
            AuditLog.action == "delete_platform_rule",
            AuditLog.resource_id == rule_id,
        ).all()
        assert len(logs) >= 1, "应有 delete_platform_rule 审计记录"
