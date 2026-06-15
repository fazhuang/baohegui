"""安全测试 — 鉴权边界：跨用户访问拒绝

覆盖：
- user_b 不能访问 user_a 的报告 (detail/pdf/export/list)
- user_b 不能用 user_a 的文件发起检查
- user_b 不能给 user_a 的报告提交反馈
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.models.document import ComplianceReport, DocumentSection, UploadedFile
from app.models.user import User


def _create_user(db, username: str, role: str = "user") -> User:
    """创建测试用户并返回"""
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


def _create_file(db, user: User, filename: str = "test.pdf") -> UploadedFile:
    """创建测试文件记录"""
    f = UploadedFile(
        user_id=user.id,
        filename=filename,
        file_size=1024,
        file_hash="abc123",
        page_count=10,
        storage_path="uploads/test.docx",
        status="uploaded",
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def _create_report(db, file: UploadedFile, user: User) -> ComplianceReport:
    """创建测试报告"""
    r = ComplianceReport(
        file_id=file.id,
        total_score=85.0,
        section_score=90.0,
        violation_count=2,
        report_data=json.dumps({"test": True, "rule_violations": [], "llm_violations": []},
                               ensure_ascii=False),
        checked_by=user.id,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _headers(user: User) -> dict:
    token = create_access_token(user_id=user.id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


class TestReportCrossUser:
    """跨用户报告访问拒绝"""

    def test_user_b_cannot_read_user_a_report(self, client: TestClient, db_session):
        user_a = _create_user(db_session, "user_a_report")
        user_b = _create_user(db_session, "user_b_report")
        file_a = _create_file(db_session, user_a)
        report_a = _create_report(db_session, file_a, user_a)

        # user_b 访问 user_a 的报告 -> 403
        resp = client.get(f"/api/report/{report_a.id}", headers=_headers(user_b))
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_user_b_cannot_download_user_a_pdf(self, client: TestClient, db_session):
        user_a = _create_user(db_session, "user_a_pdf")
        user_b = _create_user(db_session, "user_b_pdf")
        file_a = _create_file(db_session, user_a)
        report_a = _create_report(db_session, file_a, user_a)

        resp = client.get(f"/api/report/{report_a.id}/pdf", headers=_headers(user_b))
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_user_b_cannot_export_user_a_excel(self, client: TestClient, db_session):
        user_a = _create_user(db_session, "user_a_excel")
        user_b = _create_user(db_session, "user_b_excel")
        file_a = _create_file(db_session, user_a)
        report_a = _create_report(db_session, file_a, user_a)

        resp = client.get(f"/api/report/{report_a.id}/export", headers=_headers(user_b))
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_user_b_cannot_see_user_a_in_list(self, client: TestClient, db_session):
        user_a = _create_user(db_session, "user_a_list")
        user_b = _create_user(db_session, "user_b_list")
        file_a = _create_file(db_session, user_a)
        _create_report(db_session, file_a, user_a)
        # user_b also creates a report
        file_b = _create_file(db_session, user_b, "b_file.pdf")
        report_b = _create_report(db_session, file_b, user_b)

        resp = client.get("/api/report/list/", headers=_headers(user_b))
        assert resp.status_code == 200
        data = resp.json()
        # user_b should only see their own report
        ids = [item["id"] for item in data["items"]]
        assert report_b.id in ids
        # user_a's report should NOT be visible
        # (report_a id may be 1, report_b id may be 2)
        report_a_ids = [i for item in data["items"] for i in [item["id"]]]
        # ensure no user_a items
        for item in data["items"]:
            assert item.get("file_name") != file_a.filename, f"user_b should not see user_a's file"

    def test_user_b_cannot_feedback_on_user_a_report(self, client: TestClient, db_session):
        user_a = _create_user(db_session, "user_a_fb")
        user_b = _create_user(db_session, "user_b_fb")
        file_a = _create_file(db_session, user_a)
        report_a = _create_report(db_session, file_a, user_a)

        resp = client.post("/api/report/feedback", json={
            "report_id": report_a.id,
            "rule_id": "R001",
            "feedback_type": "confirm",
        }, headers=_headers(user_b))
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_user_a_can_access_own_report(self, client: TestClient, db_session):
        """user_a 应该能访问自己的报告（正向验证）"""
        user_a = _create_user(db_session, "user_a_own")
        file_a = _create_file(db_session, user_a)
        report_a = _create_report(db_session, file_a, user_a)

        resp = client.get(f"/api/report/{report_a.id}", headers=_headers(user_a))
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


class TestCheckCrossUser:
    """跨用户检查拒绝"""

    def test_user_b_cannot_check_user_a_file(self, client: TestClient, db_session):
        user_a = _create_user(db_session, "user_a_check")
        user_b = _create_user(db_session, "user_b_check")
        file_a = _create_file(db_session, user_a)

        resp = client.post(f"/api/check/{file_a.id}", headers=_headers(user_b))
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_user_b_cannot_get_user_a_check_status(self, client: TestClient, db_session):
        """user_b 不能获取 user_a 的检查进度状态"""
        user_a = _create_user(db_session, "user_a_check")
        user_b = _create_user(db_session, "user_b_check")
        file_a = _create_file(db_session, user_a)

        resp = client.get(f"/api/check/{file_a.id}/status", headers=_headers(user_b))
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_user_a_can_get_own_check_status(self, client: TestClient, db_session):
        """user_a 应该能获取自己的检查进度状态"""
        user_a = _create_user(db_session, "user_a_own_st")
        file_a = _create_file(db_session, user_a)

        resp = client.get(f"/api/check/{file_a.id}/status", headers=_headers(user_a))
        assert resp.status_code == 200

    def test_admin_can_get_any_check_status(self, client: TestClient, db_session):
        """admin 能获取任何用户的检查进度状态"""
        user_a = _create_user(db_session, "user_a_admin_st")
        admin = _create_user(db_session, "admin_st", role="admin")
        file_a = _create_file(db_session, user_a)

        resp = client.get(f"/api/check/{file_a.id}/status", headers=_headers(admin))
        assert resp.status_code == 200


class TestAnonymousAccess:
    """匿名访问全部拒绝"""

    def test_anonymous_cannot_access_report(self, client: TestClient, db_session):
        user = _create_user(db_session, "user_for_anon")
        file = _create_file(db_session, user)
        report = _create_report(db_session, file, user)
        resp = client.get(f"/api/report/{report.id}")
        # Anonymous gets 401 (not authenticated) — both 401 and 403 are acceptable denials
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}: {resp.text}"

    def test_anonymous_cannot_list_reports(self, client: TestClient):
        resp = client.get("/api/report/list/")
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}: {resp.text}"

    def test_anonymous_cannot_upload(self, client: TestClient):
        resp = client.post("/api/upload/")
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}: {resp.text}"

    def test_anonymous_cannot_check(self, client: TestClient, db_session):
        user = _create_user(db_session, "user_check_anon")
        file = _create_file(db_session, user)
        resp = client.post(f"/api/check/{file.id}")
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}: {resp.text}"


class TestUploadCrossUser:
    """跨用户上传进度状态拒绝"""

    def test_user_b_cannot_get_user_a_upload_status(self, client: TestClient, db_session):
        """user_b 不能获取 user_a 的上传进度状态"""
        user_a = _create_user(db_session, "user_a_up")
        user_b = _create_user(db_session, "user_b_up")
        file_a = _create_file(db_session, user_a)

        resp = client.get(f"/api/upload/{file_a.id}/status", headers=_headers(user_b))
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_user_a_can_get_own_upload_status(self, client: TestClient, db_session):
        """user_a 应该能获取自己的上传进度状态"""
        user_a = _create_user(db_session, "user_a_up_own")
        file_a = _create_file(db_session, user_a)

        resp = client.get(f"/api/upload/{file_a.id}/status", headers=_headers(user_a))
        assert resp.status_code == 200

    def test_admin_can_get_any_upload_status(self, client: TestClient, db_session):
        """admin 能获取任何用户的上传进度状态"""
        user_a = _create_user(db_session, "user_a_up_admin")
        admin = _create_user(db_session, "admin_up", role="admin")
        file_a = _create_file(db_session, user_a)

        resp = client.get(f"/api/upload/{file_a.id}/status", headers=_headers(admin))
        assert resp.status_code == 200

    def test_anonymous_cannot_get_upload_status(self, client: TestClient):
        """匿名用户不能获取上传进度状态"""
        resp = client.get("/api/upload/1/status")  # arbitrary file id
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"
