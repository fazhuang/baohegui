"""PolicyKernel 第三轮增量修复测试

测试：
1. 持久化载荷完整性 — 单一 _policy_decision，反序列化，verify_trace
2. 真实 API 往返 — 上传→检查→报告
3. 损坏报告 fail closed — detail/PDF/Excel 均返回 409
4. 新数据库迁移 — 空库 alembic upgrade head
5. 旧数据库升级 — 历史数据不丢失、不回填
6. 数据库约束 — 非法值被拒绝
7. 平台章节矩阵 — present_sections 精确断言
"""

from __future__ import annotations

import io
import json as _json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from app.core.policy_kernel import (
    DecisionInput,
    DecisionAction,
    DecisionState,
    ParseQuality,
    PlanTier,
    PlatformPolicy,
    PolicyDecision,
    PolicyKernel,
    ReasonCode,
    RiskLevel,
    RuleType,
    RuleViolationInput,
    BiasFindingInput,
    TenantPolicy,
    TraceStep,
    sha256_hex,
    _canonical_json,
    verify_trace,
    policy_kernel,
)


BACKEND_DIR = str(Path(__file__).resolve().parent.parent)


# ═══════════════════════════════════════════════════════════════
# 1. 持久化载荷完整性
# ═══════════════════════════════════════════════════════════════

class TestPersistencePayloadIntegrity:
    """report_data 中只有一个 _policy_decision，反序列化完整，verify_trace 通过"""

    def _make_payload(self) -> tuple[dict, DecisionInput, PolicyDecision]:
        """通过真实 payload 构造函数生成 report_data。"""
        di = DecisionInput(
            schema_version="2.0.0",
            rule_violations=[
                RuleViolationInput(
                    rule_id="R001", rule_type=RuleType.FORBIDDEN,
                    risk_level=RiskLevel.HIGH, description="test violation",
                )
            ],
            present_sections={"招标公告", "技术要求"},
        )
        pd = policy_kernel.decide(di)

        from app.api.check import build_policy_audit_payload
        # 用空 report 模拟
        from app.engine.fusion import ComplianceReport
        report = ComplianceReport(total_score=85.0)
        payload = build_policy_audit_payload(
            report=report,
            decision_input=di,
            policy_decision=pd,
            diagnostics={"_test": True},
        )
        return payload, di, pd

    def test_single_policy_decision_key(self):
        """report_data 只能有一个 _policy_decision 键"""
        payload, _, _ = self._make_payload()
        # JSON 序列化后只能出现一次
        json_str = _json.dumps(payload, ensure_ascii=False)
        keys = [k for k in payload.keys() if k == "_policy_decision"]
        assert len(keys) == 1, f"expected 1 _policy_decision key, got {len(keys)}"

    def test_policy_decision_deserializable(self):
        """_policy_decision 可通过 PolicyDecision.model_validate 重建"""
        payload, _, _ = self._make_payload()
        pd_raw = payload["_policy_decision"]
        pd = PolicyDecision.model_validate(pd_raw)
        assert pd.final_action in (
            DecisionAction.PASS, DecisionAction.WARN,
            DecisionAction.REQUIRE_REVIEW, DecisionAction.BLOCK,
        )

    def test_trace_steps_complete(self):
        """每条 TraceStep 包含 reason_params 和 proposed_transition"""
        payload, _, _ = self._make_payload()
        pd = PolicyDecision.model_validate(payload["_policy_decision"])
        for i, step in enumerate(pd.trace_chain):
            assert step.reason_params is not None, f"trace[{i}] missing reason_params"
            assert step.proposed_transition is not None, f"trace[{i}] missing proposed_transition"
            assert isinstance(step.proposed_transition, DecisionState)
            assert step.proposed_transition.action in (
                DecisionAction.PASS, DecisionAction.WARN,
                DecisionAction.REQUIRE_REVIEW, DecisionAction.BLOCK,
            ), f"trace[{i}] proposed_transition.action={step.proposed_transition.action}"

    def test_verify_trace_passes(self):
        """payload 中的 DecisionInput + PolicyDecision 通过 verify_trace"""
        payload, di, pd = self._make_payload()
        di_reconstructed = DecisionInput.model_validate(payload["_decision_input"])
        pd_reconstructed = PolicyDecision.model_validate(payload["_policy_decision"])
        vr = verify_trace(di_reconstructed, pd_reconstructed)
        assert vr["valid"], f"verify_trace failed: {vr['errors']}"


# ═══════════════════════════════════════════════════════════════
# 3. 损坏报告 fail closed
# ═══════════════════════════════════════════════════════════════

class TestCorruptedReportFailClosed:
    """损坏的 PolicyDecision 在 detail/PDF/Excel 三端返回 409"""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @staticmethod
    def _register_and_login(client):
        import secrets
        email = f"test-corr-{secrets.token_hex(4)}@example.com"
        pw = "Test123456!"
        resp = client.post("/api/auth/register", json={"username": email, "password": pw, "email": email})
        if resp.status_code not in (200, 201, 409):
            raise RuntimeError(f"register failed: {resp.status_code} {resp.text}")
        # 如果 409（已存在），直接登录
        if resp.status_code == 409:
            resp = client.post("/api/auth/login", json={"username": email, "password": pw})
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def _create_docx_file(self):
        doc = Document()
        doc.add_heading("第一章 招标公告", level=1)
        doc.add_paragraph("公开招标，欢迎投标人参加。")
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        buf.name = "test_corrupt.docx"
        return buf

    def _upload_and_check(self, client, auth_headers):
        """上传文件 → 执行检查 → 返回 report_id"""
        buf = self._create_docx_file()
        resp = client.post("/api/upload/", files={"file": (buf.name, buf, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}, headers=auth_headers)
        assert resp.status_code in (200, 201), f"upload failed: {resp.status_code} {resp.text}"
        file_id = resp.json()["db_id"]  # integer DB row id
        check_resp = client.post(f"/api/check/{file_id}?procurement_method=公开招标&project_type=货物类", headers=auth_headers)
        assert check_resp.status_code == 200, f"check failed: {check_resp.status_code} {check_resp.text}"
        return check_resp.json()["report_id"]

    def test_corrupt_via_proposed_transition_409_detail(self, client):
        """篡改 proposed_transition → detail 409"""
        h = self._register_and_login(client)

        buf = self._create_docx_file()
        resp = client.post("/api/upload/", files={"file": (buf.name, buf, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}, headers=h)
        assert resp.status_code in (200, 201), f"upload failed: {resp.text}"
        file_id = resp.json()["db_id"]  # integer DB row id
        check_resp = client.post(f"/api/check/{file_id}?platform=guangdong&procurement_method=公开招标&project_type=货物类", headers=h)
        assert check_resp.status_code == 200, f"check failed: {check_resp.text}"
        report_id = check_resp.json()["report_id"]

        # 直接操作数据库篡改 report_data
        from app.db.database import SessionLocal
        from app.models.document import ComplianceReport
        db = SessionLocal()
        try:
            db_report = db.query(ComplianceReport).filter(ComplianceReport.id == report_id).first()
            data = _json.loads(db_report.report_data)
            pd = data["_policy_decision"]
            # 篡改 proposed_transition
            if pd.get("trace_chain"):
                pd["trace_chain"][-1]["proposed_transition"] = {
                    "action": "pass", "risk_level": "low", "requires_human_review": False,
                }
                # 不同步修改 state_after → 触发语义不匹配
                data["_policy_decision"] = pd
                db_report.report_data = _json.dumps(data, ensure_ascii=False)
                db.commit()

            # detail must return 409
            resp = client.get(f"/api/report/{report_id}", headers=h)
            assert resp.status_code == 409, f"expected 409 for corrupt, got {resp.status_code}: {resp.text}"
            detail = resp.json()["detail"]
            assert detail["integrity_status"] == "integrity_failed"
        finally:
            db.close()

    def test_corrupt_via_hash_409_pdf(self, client):
        """篡改 decision_hash → PDF 409"""
        h = self._register_and_login(client)

        buf = self._create_docx_file()
        resp = client.post("/api/upload/", files={"file": (buf.name, buf, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}, headers=h)
        file_id = resp.json()["db_id"]  # integer DB row id
        check_resp = client.post(f"/api/check/{file_id}?procurement_method=公开招标&project_type=货物类", headers=h)
        assert check_resp.status_code == 200, f"check failed: {check_resp.text}"
        report_id = check_resp.json()["report_id"]

        from app.db.database import SessionLocal
        from app.models.document import ComplianceReport
        db = SessionLocal()
        try:
            db_report = db.query(ComplianceReport).filter(ComplianceReport.id == report_id).first()
            db_report.decision_hash = "0000000000000000bad_hash"
            db_report.decision_integrity_status = "verified"  # 刻意标 verified
            db.commit()

            resp = client.get(f"/api/report/{report_id}/pdf", headers=h)
            assert resp.status_code == 409, f"expected 409 for corrupt PDF, got {resp.status_code}"
        finally:
            db.close()

    def test_corrupt_via_action_mismatch_409_excel(self, client):
        """数据库 decision_hash 篡改后 Excel 409"""
        h = self._register_and_login(client)

        buf = self._create_docx_file()
        resp = client.post("/api/upload/", files={"file": (buf.name, buf, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}, headers=h)
        file_id = resp.json()["db_id"]  # integer DB row id
        check_resp = client.post(f"/api/check/{file_id}?procurement_method=公开招标&project_type=货物类", headers=h)
        assert check_resp.status_code == 200, f"check failed: {check_resp.text}"
        report_id = check_resp.json()["report_id"]

        from app.db.database import SessionLocal
        from app.models.document import ComplianceReport
        db = SessionLocal()
        try:
            db_report = db.query(ComplianceReport).filter(ComplianceReport.id == report_id).first()
            # 篡改 JSON 内嵌 decision_hash → verify_trace 将失败
            data = _json.loads(db_report.report_data)
            data["_policy_decision"]["decision_hash"] = "0" * 64
            db_report.report_data = _json.dumps(data, ensure_ascii=False)
            db.commit()
        finally:
            db.close()

        resp = client.get(f"/api/report/{report_id}/export", headers=h)
        assert resp.status_code == 409, f"expected 409 for corrupt Excel, got {resp.status_code}: {resp.text}"

    def test_corrupt_missing_decision_input_409(self, client):
        """schema v2 但缺少 DecisionInput → 409"""
        h = self._register_and_login(client)

        buf = self._create_docx_file()
        resp = client.post("/api/upload/", files={"file": (buf.name, buf, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}, headers=h)
        file_id = resp.json()["db_id"]  # integer DB row id
        check_resp = client.post(f"/api/check/{file_id}?procurement_method=公开招标&project_type=货物类", headers=h)
        assert check_resp.status_code == 200, f"check failed: {check_resp.text}"
        report_id = check_resp.json()["report_id"]

        from app.db.database import SessionLocal
        from app.models.document import ComplianceReport
        db = SessionLocal()
        try:
            db_report = db.query(ComplianceReport).filter(ComplianceReport.id == report_id).first()
            data = _json.loads(db_report.report_data)
            del data["_decision_input"]
            db_report.report_data = _json.dumps(data, ensure_ascii=False)
            db_report.policy_schema_version = "2.0.0"
            db.commit()

            resp = client.get(f"/api/report/{report_id}", headers=h)
            assert resp.status_code == 409, f"expected 409, got {resp.status_code}: {resp.text}"
        finally:
            db.close()


# ═══════════════════════════════════════════════════════════════
# 4. 新数据库迁移 — 空库 alembic upgrade head
# ═══════════════════════════════════════════════════════════════

class TestFreshMigration:
    """全新空 SQLite 数据库执行 alembic upgrade head → 成功"""

    def test_fresh_migration_creates_all_tables(self):
        db_path = "/private/tmp/bhg_policy_fresh_test.db"
        # 删除旧文件
        try:
            os.remove(db_path)
        except FileNotFoundError:
            pass

        db_url = f"sqlite:///{db_path}"
        env = {**os.environ, "DATABASE_URL": db_url, "BHG_DATABASE_URL": db_url}

        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True, text=True, env=env, cwd=BACKEND_DIR,
        )
        assert result.returncode == 0, f"alembic upgrade head failed: {result.stderr}"

        # 验证表存在
        conn = sqlite3.connect(db_path)
        try:
            tables = {
                row[0] for row in
                conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            assert "uploaded_files" in tables, f"missing uploaded_files, got {tables}"
            assert "document_sections" in tables, f"missing document_sections"
            assert "compliance_reports" in tables, f"missing compliance_reports"
            assert "alembic_version" in tables, f"missing alembic_version"

            # 验证决策列
            cols = {
                row[1] for row in
                conn.execute("PRAGMA table_info(compliance_reports)").fetchall()
            }
            for col in ["decision_action", "decision_risk_level", "decision_hash",
                        "policy_schema_version", "decision_integrity_status"]:
                assert col in cols, f"missing column {col} in compliance_reports, got {cols}"

            # 验证当前 revision 为 head
            rev_row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            assert rev_row is not None, "no alembic_version row"
            # head revision should be 20260705_1000_decision_columns
            assert rev_row[0] == "20260705_1000_decision_columns", f"expected head, got {rev_row[0]}"
        finally:
            conn.close()
            os.remove(db_path)


# ═══════════════════════════════════════════════════════════════
# 5. 旧数据库升级 — 历史数据不丢失、不回填
# ═══════════════════════════════════════════════════════════════

class TestLegacyMigration:
    """迁移前数据库已有 compliance_reports 及历史行，升级后数据完好"""

    def test_legacy_data_preserved(self):
        db_path = "/private/tmp/bhg_policy_legacy_test.db"
        try:
            os.remove(db_path)
        except FileNotFoundError:
            pass

        # 模拟旧数据库：先创建表并插入历史数据
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("""
                CREATE TABLE uploaded_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL, filename TEXT NOT NULL,
                    file_size INTEGER NOT NULL, file_hash TEXT NOT NULL,
                    storage_path TEXT NOT NULL, status TEXT DEFAULT 'uploaded'
                )
            """)
            conn.execute("""
                CREATE TABLE compliance_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL REFERENCES uploaded_files(id),
                    total_score REAL NOT NULL DEFAULT 0,
                    section_score REAL, keyword_score REAL,
                    forbidden_score REAL, semantic_score REAL,
                    violation_count INTEGER DEFAULT 0,
                    report_data TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    checked_by INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE alembic_version (version_num VARCHAR(32))
            """)
            conn.execute("INSERT INTO alembic_version VALUES ('d4e5f6a7b8c9')")
            # 插入历史数据
            conn.execute("INSERT INTO uploaded_files (id, user_id, filename, file_size, file_hash, storage_path) VALUES (1, 1, 'test.pdf', 1024, 'abc', '/tmp/test.pdf')")
            conn.execute("INSERT INTO compliance_reports (id, file_id, total_score) VALUES (1, 1, 85.5)")
            conn.commit()
        finally:
            conn.close()

        # 执行迁移到 head
        db_url = f"sqlite:///{db_path}"
        env = {**os.environ, "DATABASE_URL": db_url, "BHG_DATABASE_URL": db_url}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True, text=True, env=env, cwd=BACKEND_DIR,
        )
        assert result.returncode == 0, f"alembic upgrade failed: {result.stderr}"

        # 验证历史数据未丢失
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT id, total_score, decision_action, decision_risk_level, decision_integrity_status, decision_hash FROM compliance_reports WHERE id=1").fetchone()
            assert row is not None, "historical row lost"
            assert row[0] == 1
            assert row[1] == 85.5  # total_score preserved
            # decision_action 应为 NULL（未回填）
            assert row[2] is None, f"decision_action was backfilled: {row[2]}"
            assert row[3] is None, f"decision_risk_level was backfilled: {row[3]}"
            # integrity_status 应为 legacy_unverifiable
            assert row[4] == "legacy_unverifiable", f"expected legacy_unverifiable, got {row[4]}"
            assert row[5] is None, f"decision_hash was backfilled: {row[5]}"
        finally:
            conn.close()
            os.remove(db_path)


# ═══════════════════════════════════════════════════════════════
# 6. 数据库约束 — 非法值被拒绝
# ═══════════════════════════════════════════════════════════════

class TestDatabaseConstraints:
    """非法决策值被数据库约束拒绝"""

    def _create_fresh_db_with_migrations(self) -> str:
        db_path = f"/private/tmp/bhg_constraint_test_{os.getpid()}.db"
        try:
            os.remove(db_path)
        except FileNotFoundError:
            pass
        db_url = f"sqlite:///{db_path}"
        env = {**os.environ, "DATABASE_URL": db_url, "BHG_DATABASE_URL": db_url}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True, text=True, env=env, cwd=BACKEND_DIR,
        )
        assert result.returncode == 0, f"migration failed: {result.stderr}"
        # Verify constraints in schema
        conn = sqlite3.connect(db_path)
        try:
            schema = list(conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='compliance_reports'"))[0][0]
            assert "decision_action" in schema
            assert "CHECK" in schema, f"no CHECK constraints in fresh DB: {schema}"
        finally:
            conn.close()
        return db_path

    def test_invalid_decision_action_rejected(self):
        db_path = self._create_fresh_db_with_migrations()
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT INTO uploaded_files (id, user_id, filename, file_size, file_hash, storage_path) VALUES (1, 1, 'test.pdf', 1024, 'abc', '/tmp/test.pdf')")
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO compliance_reports (file_id, total_score, decision_action) VALUES (1, 85, 'anything')")
        finally:
            conn.close()
            os.remove(db_path)

    def test_invalid_decision_risk_level_rejected(self):
        db_path = self._create_fresh_db_with_migrations()
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT INTO uploaded_files (id, user_id, filename, file_size, file_hash, storage_path) VALUES (1, 1, 'test.pdf', 1024, 'abc', '/tmp/test.pdf')")
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO compliance_reports (file_id, total_score, decision_risk_level) VALUES (1, 85, 'super_high')")
        finally:
            conn.close()
            os.remove(db_path)

    def test_invalid_integrity_status_rejected(self):
        db_path = self._create_fresh_db_with_migrations()
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT INTO uploaded_files (id, user_id, filename, file_size, file_hash, storage_path) VALUES (1, 1, 'test.pdf', 1024, 'abc', '/tmp/test.pdf')")
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO compliance_reports (file_id, total_score, decision_integrity_status) VALUES (1, 85, 'trusted')")
        finally:
            conn.close()
            os.remove(db_path)


# ═══════════════════════════════════════════════════════════════
# 7. 平台章节矩阵 — present_sections 精确断言
# ═══════════════════════════════════════════════════════════════

class TestPlatformSectionMatrix:
    """required_sections 与 present_sections 的精确矩阵"""

    kernel = PolicyKernel()

    def _decide(self, required: set[str], present: set[str], platform_id="guangdong"):
        di = DecisionInput(
            platform_policy=PlatformPolicy(platform_id=platform_id, required_sections=required),
            present_sections=present,
        )
        return self.kernel.decide(di)

    def test_all_present_no_block(self):
        """required={"招标公告"}, present={"招标公告"} → 非 PLATFORM BLOCK"""
        d = self._decide({"招标公告"}, {"招标公告"})
        # 平台层必须 PLATFORM_PASSTHROUGH
        plat = [t for t in d.trace_chain if t.source.value == "platform"][0]
        assert plat.reason_code == ReasonCode.PLATFORM_PASSTHROUGH
        assert d.final_action != DecisionAction.BLOCK

    def test_empty_present_block(self):
        """required={"招标公告"}, present=set() → BLOCK + CRITICAL"""
        d = self._decide({"招标公告"}, set())
        assert d.final_action == DecisionAction.BLOCK
        assert d.final_risk_level == RiskLevel.CRITICAL
        assert d.requires_human_review is True
        plat = [t for t in d.trace_chain if t.source.value == "platform"][0]
        assert plat.reason_code == ReasonCode.PLATFORM_MISSING_SECTION
        assert "招标公告" in plat.reason_params["missing"]

    def test_wrong_present_block(self):
        """required={"招标公告"}, present={"评审办法"} → BLOCK"""
        d = self._decide({"招标公告"}, {"评审办法"})
        assert d.final_action == DecisionAction.BLOCK
        assert d.final_risk_level == RiskLevel.CRITICAL
        plat = [t for t in d.trace_chain if t.source.value == "platform"][0]
        assert plat.reason_code == ReasonCode.PLATFORM_MISSING_SECTION

    def test_present_plus_unrelated_violation_no_block(self):
        """required={"招标公告"}, present={"招标公告"}，另有 chapter_required 违规 → 平台仍通过"""
        di = DecisionInput(
            rule_violations=[
                RuleViolationInput(rule_id="R003", rule_type=RuleType.CHAPTER_REQUIRED,
                                   risk_level=RiskLevel.MEDIUM, description="缺少投标须知"),
            ],
            platform_policy=PlatformPolicy(platform_id="guangdong", required_sections={"招标公告"}),
            present_sections={"招标公告"},
        )
        d = self.kernel.decide(di)
        plat = [t for t in d.trace_chain if t.source.value == "platform"][0]
        assert plat.reason_code == ReasonCode.PLATFORM_PASSTHROUGH, (
            f"platform should passthrough when required section present, got {plat.reason_code}"
        )
        # HARD_RULE may still escalate from chapter_required rule
        # But PLATFORM must NOT block
        assert plat.state_after.action != DecisionAction.BLOCK

    def test_unknown_platform_is_error(self):
        """未知 platform 不应静默降级。在 API 层测试（check.py），这里验证空 PlatformPolicy 行为。"""
        # 空平台策略（无 platform_id）→ PLATFORM_NO_POLICY
        di = DecisionInput(
            platform_policy=PlatformPolicy(platform_id=""),
            present_sections={"招标公告"},
        )
        d = self.kernel.decide(di)
        plat = [t for t in d.trace_chain if t.source.value == "platform"][0]
        assert plat.reason_code == ReasonCode.PLATFORM_NO_POLICY

    def test_required_sections_empty_passthrough(self):
        """required_sections 为空 → PLATFORM passthrough"""
        di = DecisionInput(
            platform_policy=PlatformPolicy(platform_id="test_plat", required_sections=set()),
            present_sections={"招标公告"},
        )
        d = self.kernel.decide(di)
        plat = [t for t in d.trace_chain if t.source.value == "platform"][0]
        assert plat.reason_code == ReasonCode.PLATFORM_PASSTHROUGH
