"""P0 回归测试：跨用户数据越权访问 (IDOR)

验证 report/view/pdf/excel 端点拒绝用户 A 读取用户 B 的合规报告。
"""

import json
import pytest
from fastapi import status

from app.models.document import ComplianceReport, UploadedFile
from app.models.user import User


# ── test fixtures ─────────────────────────────────────────────

@pytest.fixture
def user_a(db_session):
    """用户 A — 普通用户"""
    from app.core.security import hash_password
    user = User(
        username="user_a",
        hashed_password=hash_password("test123"),
        role="user",
        company="A公司",
        email="usera@test.com",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def user_b(db_session):
    """用户 B — 另一个普通用户"""
    from app.core.security import hash_password
    user = User(
        username="user_b",
        hashed_password=hash_password("test123"),
        role="user",
        company="B公司",
        email="userb@test.com",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def user_a_token(user_a):
    """用户 A 的 JWT token"""
    from app.core.security import create_access_token
    return create_access_token(user_id=user_a.id, role="user")


@pytest.fixture
def user_b_token(user_b):
    """用户 B 的 JWT token"""
    from app.core.security import create_access_token
    return create_access_token(user_id=user_b.id, role="user")


@pytest.fixture
def a_headers(user_a_token):
    return {"Authorization": f"Bearer {user_a_token}"}


@pytest.fixture
def b_headers(user_b_token):
    return {"Authorization": f"Bearer {user_b_token}"}


@pytest.fixture
def b_report(db_session, user_b):
    """用户 B 创建的合规报告"""
    f = UploadedFile(
        filename="b_report.docx",
        file_size=1024,
        file_hash="abc123",
        storage_path="uploads/b_report.docx",
        user_id=user_b.id,
    )
    db_session.add(f)
    db_session.commit()

    # 使用 PolicyKernel 生成真实的、可验证的 PolicyDecision
    from app.core.policy_kernel import DecisionInput, policy_kernel
    di = DecisionInput()
    pd = policy_kernel.decide(di)

    report = ComplianceReport(
        file_id=f.id,
        checked_by=user_b.id,
        total_score=85.0,
        violation_count=3,
        policy_schema_version=pd.schema_version,
        decision_action=pd.final_action.value,
        decision_risk_level=pd.final_risk_level.value,
        decision_requires_human_review=pd.requires_human_review,
        decision_hash=pd.decision_hash,
        decision_integrity_status="verified",
        report_data=json.dumps({
            "total_score": 85.0, "risk_level": "medium",
            "risks": [], "sections": [],
            "_decision_input": di.model_dump(mode="json"),
            "_policy_decision": pd.model_dump(mode="json"),
        }),
    )
    db_session.add(report)
    db_session.commit()
    db_session.refresh(report)
    return report


class TestIDOR:
    """P0: 跨用户数据访问控制验证"""

    # ── 报告详情 ─────────────────────────────────────────

    def test_user_a_cannot_view_user_b_report(self, client, a_headers, b_report):
        """用户 A 不能查看用户 B 的报告"""
        resp = client.get(f"/api/report/{b_report.id}", headers=a_headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_user_a_cannot_download_user_b_pdf(self, client, a_headers, b_report):
        """用户 A 不能下载用户 B 的 PDF"""
        resp = client.get(f"/api/report/{b_report.id}/pdf", headers=a_headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_user_a_cannot_export_user_b_excel(self, client, a_headers, b_report):
        """用户 A 不能导出用户 B 的 Excel"""
        resp = client.get(f"/api/report/{b_report.id}/export", headers=a_headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_user_b_can_access_own_report(self, client, b_headers, b_report):
        """用户 B 可以访问自己的报告（正向验证）"""
        resp = client.get(f"/api/report/{b_report.id}", headers=b_headers)
        assert resp.status_code == status.HTTP_200_OK

    def test_user_b_can_download_own_pdf(self, client, b_headers, b_report):
        """用户 B 可以下载自己的 PDF（正向验证）"""
        resp = client.get(f"/api/report/{b_report.id}/pdf", headers=b_headers)
        assert resp.status_code == status.HTTP_200_OK

    def test_user_b_can_export_own_excel(self, client, b_headers, b_report):
        """用户 B 可以导出自己的 Excel（正向验证）"""
        resp = client.get(f"/api/report/{b_report.id}/export", headers=b_headers)
        assert resp.status_code == status.HTTP_200_OK

    # ── 报告列表 ─────────────────────────────────────────

    def test_list_reports_filters_by_owner(self, client, a_headers, b_headers, b_report, user_a, db_session):
        """普通用户 list 只返回自己的报告"""
        # 为用户 A 也创建一份报告
        f = UploadedFile(
            filename="a_report.docx", file_size=1024,
            file_hash="def456", storage_path="uploads/a_report.docx",
            user_id=user_a.id,
        )
        db_session.add(f)
        db_session.commit()
        a_report = ComplianceReport(
            file_id=f.id, checked_by=user_a.id,
            total_score=90.0, violation_count=1,
            report_data=json.dumps({"total_score": 90.0}),
        )
        db_session.add(a_report)
        db_session.commit()

        # 用户 A 的列表不应包含用户 B 的报告
        resp = client.get("/api/report/list/", headers=a_headers)
        assert resp.status_code == 200
        data = resp.json()
        a_ids = {item["id"] for item in data["items"]}
        assert a_report.id in a_ids
        assert b_report.id not in a_ids

    # ── 未认证访问 ──────────────────────────────────────

    def test_report_detail_requires_auth(self, client, b_report):
        """未认证用户无法访问任何报告"""
        resp = client.get(f"/api/report/{b_report.id}")
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_report_pdf_requires_auth(self, client, b_report):
        """未认证用户无法下载 PDF"""
        resp = client.get(f"/api/report/{b_report.id}/pdf")
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_report_excel_requires_auth(self, client, b_report):
        """未认证用户无法导出 Excel"""
        resp = client.get(f"/api/report/{b_report.id}/export")
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    # ── 管理员可以访问所有报告 ────────────────────────────

    def test_admin_can_view_any_report(self, client, auth_headers, b_report):
        """管理员可以查看任意用户报告"""
        resp = client.get(f"/api/report/{b_report.id}", headers=auth_headers)
        assert resp.status_code == status.HTTP_200_OK

    # ── 不存在的报告 ────────────────────────────────────

    def test_nonexistent_report_returns_404(self, client, a_headers):
        """不存在报告返回 404（非 403 — 防止信息泄漏）"""
        resp = client.get("/api/report/99999", headers=a_headers)
        assert resp.status_code == status.HTTP_404_NOT_FOUND
