"""MinIO 对象存储服务 - 文件上传/下载/删除"""

import io
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

logger = logging.getLogger(__name__)


class MinioService:
    """MinIO 客户端封装

    使用方式::

        minio = MinioService()
        minio.upload("uploads/abc.pdf", data, "application/pdf")
        minio.download("uploads/abc.pdf", "/tmp/abc.pdf")
    """

    def __init__(self):
        self._client: Optional[Minio] = None
        self._bucket_exists = False

    @property
    def client(self) -> Minio:
        if self._client is None:
            import urllib3
            http_client = urllib3.PoolManager(
                timeout=urllib3.Timeout(
                    connect=settings.minio_connect_timeout,
                    read=30,
                ),
            )
            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=False,
                http_client=http_client,
            )
        return self._client

    def ensure_bucket(self) -> None:
        """确保 bucket 存在，不存在则创建"""
        if self._bucket_exists:
            return
        try:
            found = self.client.bucket_exists(settings.minio_bucket)
            if not found:
                self.client.make_bucket(settings.minio_bucket)
                logger.info("MinIO bucket '%s' 已创建", settings.minio_bucket)
            else:
                logger.info("MinIO bucket '%s' 已就绪", settings.minio_bucket)
            self._bucket_exists = True
        except S3Error as e:
            logger.error("MinIO bucket 初始化失败: %s", e)
            raise

    def upload(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """上传数据到 MinIO

        Args:
            object_key: 对象键（如 uploads/abc.pdf）
            data: 二进制数据
            content_type: MIME 类型

        Returns:
            对象键
        """
        try:
            self.client.put_object(
                settings.minio_bucket,
                object_key,
                io.BytesIO(data),
                len(data),
                content_type=content_type,
            )
            logger.info("MinIO 上传成功: %s (%d bytes)", object_key, len(data))
            return object_key
        except S3Error as e:
            logger.error("MinIO 上传失败 %s: %s", object_key, e)
            raise

    def download(self, object_key: str, target_path: str) -> str:
        """下载对象到本地路径

        Args:
            object_key: 对象键
            target_path: 本地目标路径

        Returns:
            本地文件路径
        """
        try:
            self.client.fget_object(settings.minio_bucket, object_key, target_path)
            logger.info("MinIO 下载成功: %s -> %s", object_key, target_path)
            return target_path
        except S3Error as e:
            logger.error("MinIO 下载失败 %s: %s", object_key, e)
            raise

    def delete(self, object_key: str) -> None:
        """删除对象"""
        try:
            self.client.remove_object(settings.minio_bucket, object_key)
            logger.info("MinIO 删除成功: %s", object_key)
        except S3Error as e:
            logger.error("MinIO 删除失败 %s: %s", object_key, e)
            raise

    @contextmanager
    def local_path(self, storage_path: str):
        """获取存储路径的本地文件句柄（自动判断 MinIO vs 本地）

        - MinIO 对象键（以 'uploads/' 开头）：下载到临时文件，退出时自动删除
        - 本地路径（以 '/' 开头）：直接返回路径

        使用方式::

            with minio_service.local_path(db_file.storage_path) as local:
                parsed = parser.parse(local)
        """
        if storage_path.startswith("uploads/"):
            # MinIO 对象键 → 下载到临时文件
            suffix = Path(storage_path).suffix
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp_path = tmp.name
            tmp.close()
            try:
                self.download(storage_path, tmp_path)
                yield tmp_path
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        else:
            # 本地文件路径 → 直接使用
            yield storage_path


# 模块级单例
minio_service = MinioService()
