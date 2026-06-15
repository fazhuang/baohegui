"""安全测试 — 上传安全基线

覆盖：
- 流式分块读取（不一次性 read）
- 超过大小限制被拒绝
- 伪装 MIME/扩展名但魔数错误被拒绝
- 空文件被拒绝
- 不支持扩展名被拒绝
- 魔数实际不匹配时被拒绝
"""

import io
import pytest
import zipfile
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
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


def _headers(user: User) -> dict:
    token = create_access_token(user_id=user.id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


class TestUploadSecurity:
    """上传安全测试"""

    def test_reject_oversized_file(self, client: TestClient, db_session):
        """超过 50MB 文件应被拒绝"""
        user = _create_user(db_session, "upload_oversize")
        # 创建一个超过限制的文件流
        fake_content = b"%PDF-1.4\n" + b"x" * (51 * 1024 * 1024)  # 51MB
        resp = client.post(
            "/api/upload/",
            files={"file": ("big.pdf", io.BytesIO(fake_content), "application/pdf")},
            headers=_headers(user),
        )
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        assert "超过限制" in resp.json()["detail"]

    def test_reject_wrong_magic_bytes(self, client: TestClient, db_session):
        """伪装成 PDF 但实际上传的是纯文本"""
        user = _create_user(db_session, "upload_magic")
        fake_content = b"Hello, I am not a real PDF!"
        resp = client.post(
            "/api/upload/",
            files={"file": ("fake.pdf", io.BytesIO(fake_content), "application/pdf")},
            headers=_headers(user),
        )
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        assert "无法识别" in resp.json()["detail"] or "格式" in resp.json()["detail"]

    def test_reject_empty_file(self, client: TestClient, db_session):
        """空文件应被拒绝"""
        user = _create_user(db_session, "upload_empty")
        resp = client.post(
            "/api/upload/",
            files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
            headers=_headers(user),
        )
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        assert "空" in resp.json()["detail"]

    def test_reject_unsupported_extension(self, client: TestClient, db_session):
        """不支持的文件扩展名应被拒绝"""
        user = _create_user(db_session, "upload_ext")
        resp = client.post(
            "/api/upload/",
            files={"file": ("test.exe", io.BytesIO(b"test"), "application/octet-stream")},
            headers=_headers(user),
        )
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        assert "不支持" in resp.json()["detail"]

    def test_magic_bytes_override_extension(self, client: TestClient, db_session):
        """扩展名为 .pdf 但实际是 DOCX 的 ZIP 文件 → 以魔数为准（DOCX 内部需要 [Content_Types].xml）"""
        user = _create_user(db_session, "upload_magic_override")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
                "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
                "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
                "</Types>",
            )
            zf.writestr("word/document.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>test</w:t></w:r></w:p></w:body></w:document>')
        content = buf.getvalue()
        resp = client.post(
            "/api/upload/",
            files={"file": ("test.pdf", io.BytesIO(content), "application/pdf")},
            headers=_headers(user),
        )
        # 扩展名与魔数不符 → 严格拒绝，应返回 400
        assert resp.status_code == 400, f"Expected 400 for extension/magic mismatch, got {resp.status_code}"
        assert "不一致" in resp.json()["detail"]