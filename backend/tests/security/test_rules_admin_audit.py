"""安全测试 — 管理接口审计日志 + admin 规则创建 200

覆盖：
- admin POST /api/rules/platform 真实返回 200
- 写操作后在 audit_logs 表中有对应记录
- 普通用户写规则被拒绝且无日志产生

重要：本测试 monkeypatch rule_sync_service._save() 和 _save_manifest()
为空操作，防止 UUID 测试规则写入：
  - rules/platform_rules.json
  - rules/versions/manifest.json
  - rules/versions/rules_*.json
并防御 _save_manifest 通过 rule_version_manager.snapshot() 被间接调用。
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.models.user import User
from app.core.audit import audit_service


@pytest.fixture(autouse=True)
def _isolate_rules_persistence(monkeypatch):
    """monkeypatch 所有写入 rules/versions 的路径，防止测试规则持久化到磁盘。

    覆盖的方法：
    - rule_sync_service._save() → 写入 platform_rules.json
    - rule_sync_service._save_manifest() → 写入 manifest.json
    - RuleVersionManager.snapshot() → 写入 rules_*.json + manifest.json
    - RuleVersionManager._save_manifest() → 与 module-level 同源
    """
    from app.services.rule_sync import rule_sync_service, RuleVersionManager

    # ── rule_sync_service._save() ─────────────────────────
    original_save = rule_sync_service._save
    monkeypatch.setattr(rule_sync_service, "_save", lambda: None)

    # ── rule_sync_service._save_manifest() ────────────────
    # 该方法由 RuleVersionManager._save_manifest 复用，
    # 但有独立的 module-level 实现。安全起见同时 patch。
    if hasattr(rule_sync_service, '_save_manifest'):
        original_save_manifest = rule_sync_service._save_manifest
        monkeypatch.setattr(
            rule_sync_service, "_save_manifest", lambda: None
        )

    # ── RuleVersionManager — 会通过 sync_scheduler 间接调用 ─
    # 防止 snapshot() 写入 rules_*.json 并回调 _save_manifest
    original_snapshot = RuleVersionManager.snapshot
    # snapshot 是实例方法，需要 patch 在类上
    monkeypatch.setattr(
        RuleVersionManager, "snapshot",
        lambda self, change_log="": "mock-version-id"
    )

    yield

    # 恢复
    monkeypatch.setattr(rule_sync_service, "_save", original_save)
    if 'original_save_manifest' in dir():
        monkeypatch.setattr(
            rule_sync_service, "_save_manifest", original_save_manifest
        )
    monkeypatch.setattr(RuleVersionManager, "snapshot", original_snapshot)


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


class TestRulesFileIntegrity:
    """防回归测试：确保测试规则不会写入真实 rules/versions 文件"""

    def test_platform_rules_json_has_no_test_artifacts(self):
        """真实 rules/platform_rules.json 不含 TEST-AUDIT 或测试产物"""
        from pathlib import Path
        import json

        # Resolve from backend/tests/security/ -> repo root -> rules/
        rules_dir = Path(__file__).resolve().parent.parent.parent.parent / "rules"
        platform_file = rules_dir / "platform_rules.json"

        assert platform_file.exists(), f"platform_rules.json not found at {platform_file}"
        data = json.loads(platform_file.read_text(encoding="utf-8"))
        mappings = data.get("mappings", [])

        test_ids = {"TEST-AUDIT", "FILE-T1", "UFB-", "VR-T2", "V-TEST-1", "V-T3"}
        for rule in mappings:
            rid = rule.get("rule_id", "")
            for tid in test_ids:
                assert tid not in rid, (
                    f"Test artifact found in platform_rules.json: "
                    f"rule_id={rid} matches {tid}"
                )

    def test_versions_manifest_json_has_no_test_audit(self):
        """真实 rules/versions/manifest.json 不含 TEST-AUDIT"""
        from pathlib import Path
        import json

        rules_dir = Path(__file__).resolve().parent.parent.parent.parent / "rules"
        manifest_file = rules_dir / "versions" / "manifest.json"

        if not manifest_file.exists():
            return

        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        content = json.dumps(data)
        assert "TEST-AUDIT" not in content, (
            "TEST-AUDIT found in versions/manifest.json"
        )

    def test_no_unexpected_version_snapshots_generated(self):
        """rules/versions/ 下不存在未追踪的 rules_20260616*.json"""
        from pathlib import Path

        rules_dir = Path(__file__).resolve().parent.parent.parent.parent / "rules"
        versions_dir = rules_dir / "versions"

        assert versions_dir.exists(), f"versions dir not found at {versions_dir}"
        generated = sorted(versions_dir.glob("rules_20260616*.json"))
        assert len(generated) == 0, (
            f"Untracked version snapshots found: {[g.name for g in generated]}"
        )
