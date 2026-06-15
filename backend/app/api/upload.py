"""文件上传 API — 流式写临时文件 + 魔数校验 + 配额检查

无全量内存拼接：边读边写临时文件，滚动计算 SHA256。
"""

import hashlib
import logging
import os as _os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user, assert_resource_access
from app.db.database import get_db
from app.models.document import UploadedFile
from app.services.minio_service import minio_service
from app.services.parser import parser
from app.services.quota_service import check_quota, consume_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/upload", tags=["upload"])

# 分块大小：64KB
_CHUNK_SIZE = 64 * 1024
# 魔数检测所需最小字节数
_MAGIC_MIN_BYTES = 4096

_MAGIC_BYTES: dict[str, bytes] = {
    "pdf": b"%PDF",
    "docx": b"PK\x03\x04",
}

# ── 上传进度内存存储 ──────────────────────────────────────────
_upload_progress: dict[int, dict] = {}
_progress_lock = threading.Lock()
_PROGRESS_TTL = 300  # 5 分钟后自动清理


def _set_upload_progress(file_id: int, **kwargs) -> None:
    with _progress_lock:
        entry = _upload_progress.setdefault(file_id, {})
        entry.update(kwargs)
        entry["_updated"] = time.time()


def _get_upload_progress(file_id: int) -> dict | None:
    with _progress_lock:
        entry = _upload_progress.get(file_id)
        if entry and time.time() - entry.get("_updated", 0) > _PROGRESS_TTL:
            del _upload_progress[file_id]
            return None
        return entry


def _object_key(file_id: str, filename: str) -> str:
    safe_filename = Path(filename).name
    return f"uploads/{file_id}_{safe_filename}"


def _detect_file_type(head: bytes) -> Optional[str]:
    """通过魔数检测文件真实类型"""
    if head[:4] == _MAGIC_BYTES["pdf"]:
        return "pdf"
    if head[:4] == _MAGIC_BYTES["docx"]:
        if b"[Content_Types].xml" in head:
            return "docx"
        return None
    return None


@router.post("/")
async def upload_file(
    file: UploadFile,
    industry: Optional[str] = Form(
        default=None, description="行业标识，如 it/construction/healthcare，支持逗号分隔多选"
    ),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """上传招标文件 — 流式写临时文件（零全量内存拼接），滚动 SHA256"""
    user_id = int(user["sub"])
    max_size = settings.max_file_size_mb * 1024 * 1024

    # ── 配额检查 ──
    quota = check_quota(db, user_id)
    if quota["exhausted"]:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"本月配额已用完（{quota['files_limit']} 份）。如需更多配额，请联系升级。",
        )

    # 扩展名辅助检查
    filename = file.filename or ""
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件格式: {ext}，仅支持 {', '.join(settings.allowed_extensions)}",
        )

    # ── 流式写临时文件 + 滚动 SHA256 + 进度追踪 ──
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".upload")
    hasher = hashlib.sha256()
    total_size = 0
    head_bytes: Optional[bytes] = None

    # 临时进度 token（db 记录尚未创建，用 file_id 占位）
    _set_upload_progress(-1, stage="uploading", bytes_read=0, filename=filename)

    try:
        while True:
            chunk = await file.read(_CHUNK_SIZE)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > max_size:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"文件大小超过限制 ({settings.max_file_size_mb}MB)",
                )
            # 滚动 hash
            hasher.update(chunk)
            # 写临时文件
            _os.write(tmp_fd, chunk)
            if head_bytes is None:
                head_bytes = chunk
            # 上报进度（每 256KB 更新一次，减少锁竞争）
            if total_size % (256 * 1024) < _CHUNK_SIZE:
                _set_upload_progress(-1, stage="uploading", bytes_read=total_size, filename=filename)

        _os.close(tmp_fd)

    except HTTPException:
        _os.close(tmp_fd)
        Path(tmp_path).unlink(missing_ok=True)
        _set_upload_progress(-1, stage="error", filename=filename)
        raise
    except Exception:
        _os.close(tmp_fd)
        Path(tmp_path).unlink(missing_ok=True)
        _set_upload_progress(-1, stage="error", filename=filename)
        raise

    if head_bytes is None or total_size == 0:
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传的文件为空",
        )

    file_hash = hasher.hexdigest()

    # ── 魔数检测 ──
    detected_type = _detect_file_type(head_bytes[: min(len(head_bytes), _MAGIC_MIN_BYTES)])
    if detected_type is None:
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件格式无法识别，请上传有效的 PDF 或 DOCX 文件",
        )

    if ext and detected_type != ext:
        logger.warning(
            "文件扩展名声称 .%s 但魔数检测为 %s，拒绝上传 (user=%d, file=%s)",
            ext, detected_type, user_id, filename,
        )
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件扩展名 {ext} 与内容类型 {detected_type} 不一致，请更正后重新上传",
        )

    # 把临时文件重命名为正确的扩展名，以便 parser 识别
    correct_tmp_path = tmp_path.rsplit(".", 1)[0] + "." + detected_type
    Path(tmp_path).rename(correct_tmp_path)
    tmp_path = correct_tmp_path

    # 对象存储流上传（零全量内存读入，直接传文件路径给 MinIO fput_object）
    file_id = str(uuid.uuid4())
    storage_key = _object_key(file_id, filename)

    content_type = (
        "application/pdf"
        if ext == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    try:
        storage_path = minio_service.upload_from_path(storage_key, tmp_path, content_type=content_type)
    except Exception as e:
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件存储失败: {str(e)}",
        )

    # 解析
    db_file: Optional[UploadedFile] = None
    try:
        try:
            parsed = parser.parse(tmp_path)
            page_count = parsed.page_count
        except Exception as e:
            try:
                minio_service.delete(storage_path)
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"文件解析失败: {str(e)}",
            )

        industries: list[str] = []
        if industry:
            industries = [ind.strip() for ind in industry.split(",") if ind.strip()]

        db_file = UploadedFile(
            user_id=int(user["sub"]),
            filename=filename,
            file_size=total_size,
            file_hash=file_hash,
            page_count=page_count,
            storage_path=storage_path,
            status="uploaded",
        )
        db.add(db_file)
        db.commit()
        db.refresh(db_file)

        from app.models.document import DocumentSection
        for sec in parsed.raw_sections:
            db_section = DocumentSection(
                file_id=db_file.id,
                section_type=sec.section_type,
                title=sec.title,
                content=sec.content,
                page_start=sec.page_start,
                page_end=sec.page_end,
            )
            db.add(db_section)
        db.commit()

    except HTTPException:
        raise
    except Exception as e:
        if db_file:
            try:
                db_file.status = "failed"
                db_file.error_message = f"上传处理失败: {str(e)}"
                db.commit()
            except Exception:
                pass
        try:
            minio_service.delete(storage_path)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上传处理失败: {str(e)}",
        )
    finally:
        # 清理临时文件
        Path(tmp_path).unlink(missing_ok=True)

    consume_file(db, user_id)

    return {
        "file_id": file_id,
        "db_id": db_file.id,
        "filename": filename,
        "page_count": page_count,
        "sections": parsed.to_dict().get("sections", {}),
        "industry": industries or None,
    }


@router.get("/{file_id}/status")
async def get_upload_status(
    file_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """获取文件上传进度（轮询用）"""
    db_file = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
    if not db_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    # 仅文件所有者或管理员可以查询状态
    if db_file.user_id != int(user["sub"]) and user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    progress = _get_upload_progress(file_id)
    if progress:
        return progress
    return {"stage": "unknown"}
