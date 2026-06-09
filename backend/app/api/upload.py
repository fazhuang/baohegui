"""文件上传 API"""

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.document import UploadedFile
from app.services.minio_service import minio_service
from app.services.parser import parser
from app.services.quota_service import check_quota, consume_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/upload", tags=["upload"])


def _object_key(file_id: str, filename: str) -> str:
    """生成 MinIO 对象键"""
    safe_filename = Path(filename).name  # 去掉路径成分
    return f"uploads/{file_id}_{safe_filename}"


@router.post("/")
async def upload_file(
    file: UploadFile,
    industry: Optional[str] = Form(
        default=None, description="行业标识，如 it/construction/healthcare，支持逗号分隔多选"
    ),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """上传招标文件 (v2 - 已移除 200 页限制)"""
    logger.info("[DEBUG] upload_file v2 已加载, page limit 已移除")

    user_id = int(user["sub"])

    # ── 配额检查 ──────────────────────────────────────────
    quota = check_quota(db, user_id)
    if quota["exhausted"]:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"本月配额已用完（{quota['files_limit']} 份）。如需更多配额，请联系升级。",
        )

    # 验证扩展名
    filename = file.filename or ""
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件格式: {ext}，仅支持 {', '.join(settings.allowed_extensions)}",
        )

    # 验证 MIME 类型
    allowed_mime_types = {
        "pdf": ["application/pdf"],
        "docx": [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ],
    }
    content_type = (file.content_type or "").lower()
    if content_type and content_type not in allowed_mime_types.get(ext, []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件 MIME 类型不匹配: {content_type}",
        )

    # 读取文件内容
    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件大小超过限制 ({settings.max_file_size_mb}MB)",
        )

    # 计算文件哈希
    file_hash = hashlib.sha256(content).hexdigest()

    # 上传到 MinIO（或本地回退存储）
    file_id = str(uuid.uuid4())
    storage_key = _object_key(file_id, file.filename)

    content_type = (
        "application/pdf"
        if ext == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    try:
        storage_path = minio_service.upload(storage_key, content, content_type=content_type)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件存储失败: {str(e)}",
        )

    # 通过 local_path 获取本地文件用于解析
    with minio_service.local_path(storage_path) as local_path:
        try:
            parsed = parser.parse(local_path)
            page_count = parsed.page_count
        except Exception as e:
            # 解析失败时删除已存储的文件
            try:
                minio_service.delete(storage_path)
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"文件解析失败: {str(e)}",
            )

    # 归一化行业参数
    industries: list[str] = []
    if industry:
        industries = [ind.strip() for ind in industry.split(",") if ind.strip()]

    # 写入数据库
    db_file = UploadedFile(
        user_id=int(user["sub"]),
        filename=file.filename,
        file_size=len(content),
        file_hash=file_hash,
        page_count=page_count,
        storage_path=storage_path,
        status="parsing",
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)

    # 保存章节
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

    # ── 上传成功后才消耗配额（先上传→成功后消耗），避免用户因系统故障损失配额 ──
    consume_file(db, user_id)

    return {
        "file_id": file_id,
        "db_id": db_file.id,
        "filename": file.filename,
        "page_count": page_count,
        "sections": parsed.to_dict().get("sections", {}),
        "industry": industries or None,
    }
