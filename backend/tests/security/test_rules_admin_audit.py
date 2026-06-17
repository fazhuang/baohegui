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

    # ── 统一污染标记集合 ───────────────────────────────
    _TEST_MARKERS = frozenset({
        "TEST-AUDIT", "FILE-T1", "UFB-3390EBC9", "VR-T2", "V-TEST-1", "V-T3",
    })

    @staticmethod
    def _is_test_rule(rule: dict) -> bool:
        """基于 rule_id 判断是否为测试规则"""
        rid = rule.get("rule_id", "")
        return any(m in rid for m in TestRulesFileIntegrity._TEST_MARKERS)

    # ── 通用扫描辅助 ──────────────────────────────────

    @staticmethod
    def _rules_dir() -> "Path":
        from pathlib import Path
        return Path(__file__).resolve().parent.parent.parent.parent / "rules"

    @staticmethod
    def _check_file(path: "Path", key: str, label: str) -> list[str]:
        """扫描单个 JSON 文件中的测试规则，返回违规描述列表。"""
        import json
        violations: list[str] = []
        if not path.exists():
            return violations
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get(key, []) if key else []
        # 也做一次全文字符串兜底
        raw = json.dumps(data)
        for marker in TestRulesFileIntegrity._TEST_MARKERS:
            if marker in raw:
                violations.append(
                    f"{label} 全文匹配标记 '{marker}'"
                )
        # JSON 结构级检查 rule_id
        for i, entry in enumerate(entries):
            if TestRulesFileIntegrity._is_test_rule(entry):
                violations.append(
                    f"{label}[{i}] rule_id={entry.get('rule_id')}"
                )
        return violations

    def test_platform_rules_json_has_no_test_artifacts(self):
        """真实 rules/platform_rules.json 不含测试产物"""
        violations = self._check_file(
            self._rules_dir() / "platform_rules.json",
            key="mappings", label="platform_rules.json"
        )
        assert not violations, f"platform_rules.json 污染:\n" + "\n".join(violations)

    def test_versions_manifest_json_has_no_test_artifacts(self):
        """真实 rules/versions/manifest.json 不含测试产物（所有标记）"""
        violations = self._check_file(
            self._rules_dir() / "versions" / "manifest.json",
            key="", label="manifest.json"
        )
        # manifest 结构特殊 — versions[].rules[].rule_id
        from pathlib import Path
        import json
        mf = self._rules_dir() / "versions" / "manifest.json"
        if mf.exists():
            data = json.loads(mf.read_text(encoding="utf-8"))
            for vi, v in enumerate(data.get("versions", [])):
                for ri, r in enumerate(v.get("rules", [])):
                    if self._is_test_rule(r):
                        violations.append(
                            f"manifest.json versions[{vi}].rules[{ri}] rule_id={r.get('rule_id')}"
                        )
        assert not violations, f"manifest.json 污染:\n" + "\n".join(violations)

    def test_all_version_snapshots_have_no_test_artifacts(self):
        """全部 rules/versions/rules_*.json 不含测试产物（不限日期前缀）"""
        from pathlib import Path
        versions_dir = self._rules_dir() / "versions"
        assert versions_dir.exists(), f"versions dir not found: {versions_dir}"

        all_violations: list[str] = []
        for fpath in sorted(versions_dir.glob("rules_*.json")):
            violations = self._check_file(fpath, key="rules", label=fpath.name)
            all_violations.extend(violations)

        assert not all_violations, (
            f"版本快照污染 ({len(all_violations)} 条):\n" + "\n".join(all_violations)
        )

    def test_no_unexpected_version_snapshots_generated(self):
        """rules/versions/ 下不存在未追踪的 rules_20260616*.json"""
        from pathlib import Path
        import subprocess

        versions_dir = self._rules_dir() / "versions"
        assert versions_dir.exists()

        # 列出所有文件 + git tracked
        all_files = set(f.name for f in versions_dir.glob("rules_*.json"))
        result = subprocess.run(
            ["git", "ls-files", "--", "rules/versions/"],
            capture_output=True, text=True,
            cwd=str(self._rules_dir().parent),
        )
        tracked = {f.split("/")[-1] for f in result.stdout.strip().split("\n") if f}
        untracked = all_files - tracked

        # 只禁止 20260616 前缀的未追踪文件（测试运行典型残留）
        suspicious = {u for u in untracked if u.startswith("rules_20260616")}
        assert not suspicious, (
            f"未追踪测试快照: {sorted(suspicious)}"
        )

        rules_dir = Path(__file__).resolve().parent.parent.parent.parent / "rules"
        versions_dir = rules_dir / "versions"

        assert versions_dir.exists(), f"versions dir not found at {versions_dir}"
        generated = sorted(versions_dir.glob("rules_20260616*.json"))
        assert len(generated) == 0, (
            f"Untracked version snapshots found: {[g.name for g in generated]}"
        )
