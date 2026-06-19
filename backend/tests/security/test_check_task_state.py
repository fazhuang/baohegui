"""安全测试 — 检查任务状态机

覆盖：
- 任务正常结束后状态为 completed
- 解析失败后任务状态为 failed
- failed 状态包含 error_message 和 failed_at
- 任务异常后不会长期停留在 checking
- 异常场景（parser/LLM/fusion）应正确记录状态和错误信息
- 重复检查已处于 checking 状态的文件应返回 409
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.models.document import UploadedFile
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


def _create_file(db, user: User, status: str = "uploaded") -> UploadedFile:
    f = UploadedFile(
        user_id=user.id,
        filename="test.docx",
        file_size=1024,
        file_hash="abc123",
        page_count=10,
        storage_path="uploads/test.docx",
        status=status,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def _headers(user: User) -> dict:
    token = create_access_token(user_id=user.id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


class TestCheckTaskState:
    """检查任务状态机测试"""

    def test_normal_check_completes(self, client: TestClient, db_session):
        """正常检查流程后文件状态应为 completed"""
        user = _create_user(db_session, "check_state_user")
        file = _create_file(db_session, user)

        resp = client.post(f"/api/check/{file.id}", headers=_headers(user))
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        # 重新查询文件状态
        db_session.refresh(file)
        assert file.status == "completed", f"Expected 'completed', got '{file.status}'"

    def test_file_has_failed_status_field(self, client: TestClient, db_session):
        """UploadedFile 模型应有 error_message 和 failed_at 字段"""
        user = _create_user(db_session, "check_field_user")
        file = _create_file(db_session, user, status="failed")
        file.error_message = "测试失败消息"
        file.failed_at = datetime.now(timezone.utc)
        db_session.commit()
        db_session.refresh(file)

        assert file.error_message == "测试失败消息"
        assert file.failed_at is not None

    def test_check_with_invalid_file_id(self, client: TestClient, db_session):
        """检查不存在的文件应返回 404"""
        user = _create_user(db_session, "check_404_user")
        resp = client.post("/api/check/99999", headers=_headers(user))
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"

    def test_file_status_transitions(self, client: TestClient, db_session):
        """文件状态应按 uploaded → queued → checking → completed 流转"""
        user = _create_user(db_session, "check_transition_user")
        file = _create_file(db_session, user, status="uploaded")
        assert file.status == "uploaded"

        # 正常检查完成：状态机内部执行 queued → checking → completed
        resp = client.post(f"/api/check/{file.id}", headers=_headers(user))
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        db_session.refresh(file)
        assert file.status == "completed", f"Expected 'completed', got '{file.status}'"

    def test_checking_status_rejected(self, client: TestClient, db_session):
        """已处于 checking 状态时再次发起检查应返回 409"""
        user = _create_user(db_session, "check_reject_user")
        file = _create_file(db_session, user, status="checking")
        resp = client.post(f"/api/check/{file.id}", headers=_headers(user))
        assert resp.status_code == 409, f"Expected 409 for checking status, got {resp.status_code}"

    # ── 异常状态机测试（确保 DB 状态正确写入且可查询）──

    def test_parser_exception_sets_failed_status(self, client: TestClient, db_session):
        """解析失败应设置文件状态为 failed，并记录错误信息和时间戳"""
        # Patch 必须在请求之前生效，且请求必须发生在 patch 上下文中
        from app.services.parser import parser as parser_instance

        user = _create_user(db_session, "parser_except_user")
        file = _create_file(db_session, user, status="uploaded")

        with patch.object(parser_instance, 'parse') as mock_parse:
            mock_parse.side_effect = Exception("解析失败")

            resp = client.post(
                f"/api/check/{file.id}?procurement_method=单一来源",
                headers=_headers(user),
            )

        # 解析异常通过 check.py 的 HTTPException 返回 400：
        # 查看 check.py: 文件解析失败 → HTTPException 400
        # 但 general Exception → HTTPException 500
        # parse 的异常在 check.py 中被捕获为 400（文件解析失败）
        # 但如果 parse 的异常导致状态先设为 failed 再 raise HTTPException(status_code=400)
        # 实际上 check.py 在 parser 异常时返回的是 400
        # 如果 patch 后的 parse 抛出异常，check.py 捕获为 400
        assert resp.status_code in (400, 500), (
            f"解析失败应返回 400/500, got {resp.status_code}"
        )
        db_session.refresh(file)
        # 解析失败 → status 可能是 "failed" 或保持在 "checking"
        # 取决于异常处理逻辑：如果 check.py 设置为 failed → "failed"
        # 核实：check.py 在 parse 异常后设置 db_file.status = "failed" 然后 raise HTTPException 400
        # 所以 db.commit() 在异常传播前已执行
        assert file.status == "failed", f"status should be failed, got {file.status}"
        assert file.error_message is not None, "error_message 不应为空"
        assert "解析失败" in (file.error_message or ""), (
            f"error_message should mention '解析失败', got '{file.error_message}'"
        )
        assert file.failed_at is not None

    def test_llm_engine_exception_sets_failed_status(self, client: TestClient, db_session):
        """LLM 分析失败应设置文件状态为 failed，并记录错误信息和时间戳"""
        from app.engine.llm_engine import llm_engine as llm_instance

        user = _create_user(db_session, "llm_except_user")
        file = _create_file(db_session, user, status="uploaded")

        with patch.object(llm_instance, 'analyze') as mock_analyze:
            mock_analyze.side_effect = Exception("LLM分析失败")

            resp = client.post(
                f"/api/check/{file.id}?procurement_method=单一来源",
                headers=_headers(user),
            )

        assert resp.status_code == 500, f"LLM 分析失败应返回 500, got {resp.status_code}"
        db_session.refresh(file)
        assert file.status == "failed", f"status should be failed, got {file.status}"
        assert file.error_message is not None, "error_message 不应为空"
        assert file.error_message == "内部处理错误，请稍后重试"
        assert "LLM分析失败" not in file.error_message
        assert file.failed_at is not None

    def test_fusion_engine_exception_sets_failed_status(self, client: TestClient, db_session):
        """Fusion 合并失败应设置文件状态为 failed，并记录错误信息和时间戳"""
        from app.engine.fusion import fusion_engine as fusion_instance

        user = _create_user(db_session, "fusion_except_user")
        file = _create_file(db_session, user, status="uploaded")

        with patch.object(fusion_instance, 'merge') as mock_merge:
            mock_merge.side_effect = Exception("Fusion合并失败")

            resp = client.post(
                f"/api/check/{file.id}?procurement_method=单一来源",
                headers=_headers(user),
            )

        assert resp.status_code == 500, f"Fusion 合并失败应返回 500, got {resp.status_code}"
        db_session.refresh(file)
        assert file.status == "failed", f"status should be failed, got {file.status}"
        assert file.error_message is not None, "error_message 不应为空"
        assert file.error_message == "内部处理错误，请稍后重试"
        assert "Fusion合并失败" not in file.error_message
        assert file.failed_at is not None
