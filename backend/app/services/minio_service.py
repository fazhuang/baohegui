"""MinIO 对象存储服务 - 文件上传/下载/删除"""

import io
import logging
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

logger = logging.getLogger(__name__)


class MinioService:
    """MinIO 客户端封装（自动回退本地存储）

    当 settings.minio_endpoint 为空或为 Vercel 占位值时，自动使用本地文件系统
    作为存储后端，确保 Railway 等无 MinIO 服务的环境也能正常工作。

    使用方式::

        minio = MinioService()
        minio.upload("uploads/abc.pdf", data, "application/pdf")
        minio.download("uploads/abc.pdf", "/tmp/abc.pdf")
    """

    def __init__(self):
        self._client: Optional[Minio] = None
        self._bucket_exists = False

    @property
    def _use_local(self) -> bool:
        """检查是否应使用本地存储（MinIO 不可用时）"""
        endpoint = settings.minio_endpoint
        if not endpoint:
            return True
        if endpoint == "0.0.0.0:1":  # Vercel 占位值
            return True
        return False

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
        """确保 bucket 存在，不存在则创建

        本地模式下不执行任何操作（文件系统不需要 bucket）
        """
        if self._use_local:
            os.makedirs(settings.storage_dir, exist_ok=True)
            logger.info(
                "本地存储模式: %s (MinIO 未配置)",
                settings.storage_dir,
            )
            return
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
        """上传文件

        Args:
            object_key: 对象键（如 uploads/abc.pdf）
            data: 二进制数据
            content_type: MIME 类型

        Returns:
            存储路径（MinIO 模式返回 object_key，本地模式返回本地文件系统路径）
        """
        if self._use_local:
            return self._upload_local(object_key, data)
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

    def _upload_local(self, key: str, data: bytes) -> str:
        """本地文件系统上传（MinIO 不可用时的回退）

        Returns:
            本地文件的绝对路径
        """
        # 从 "uploads/uuid_filename.pdf" 提取文件名部分
        filename = os.path.basename(key)
        local_path = os.path.join(settings.storage_dir, filename)
        os.makedirs(settings.storage_dir, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(data)
        logger.info("本地存储成功: %s (%d bytes)", local_path, len(data))
        return local_path

    def download(self, object_key: str, target_path: str) -> str:
        """下载对象到本地路径"""
        if self._use_local:
            return self._download_local(object_key, target_path)
        try:
            self.client.fget_object(settings.minio_bucket, object_key, target_path)
            logger.info("MinIO 下载成功: %s -> %s", object_key, target_path)
            return target_path
        except S3Error as e:
            logger.error("MinIO 下载失败 %s: %s", object_key, e)
            raise

    def _download_local(self, object_key: str, target_path: str) -> str:
        """从本地文件系统复制（用于 local_path 上下文中从存储路径下载）"""
        shutil.copy2(object_key, target_path)
        logger.info("本地文件复制: %s -> %s", object_key, target_path)
        return target_path

    def delete(self, object_key: str) -> None:
        """删除对象"""
        if self._use_local:
            self._delete_local(object_key)
            return
        try:
            self.client.remove_object(settings.minio_bucket, object_key)
            logger.info("MinIO 删除成功: %s", object_key)
        except S3Error as e:
            logger.error("MinIO 删除失败 %s: %s", object_key, e)
            raise

    def _delete_local(self, object_key: str) -> None:
        """删除本地文件"""
        try:
            if os.path.exists(object_key):
                os.remove(object_key)
                logger.info("本地文件删除成功: %s", object_key)
        except OSError as e:
            logger.error("本地文件删除失败 %s: %s", object_key, e)
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
