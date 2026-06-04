"""应用配置管理"""

import os
import secrets
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 应用
    app_name: str = "包合规"
    app_version: str = "0.1.0"
    debug: bool = False

    # 数据库
    database_url: str = "postgresql://baohegui:baohegui@localhost:5432/baohegui"

    # MinIO / 对象存储
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "baohegui"
    minio_secret_key: str = "baohegui"
    minio_bucket: str = "baohegui-files"

    # JWT
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8小时

    # CORS — 允许的前端来源（逗号分隔，生产环境必填）
    cors_origins: str = ""

    # 大模型 API
    llm_provider: str = "openai_compatible"  # openai_compatible / ollama / mock
    llm_api_base: str = "http://localhost:11434/v1"  # Ollama / OpenAI 兼容 API 地址
    llm_api_key: str = ""                           # API 密钥（Ollama 可不填）
    llm_model: str = "qwen2.5:14b"                  # 模型名称
    llm_max_tokens: int = 4096                      # 单次最大生成 Token
    llm_temperature: float = 0.1                    # 生成温度（合规审查用低温）
    llm_timeout: int = 120                          # API 超时（秒）
    llm_mock_mode: bool = False                     # 是否使用 mock（开发用，生产环境必须为 False）
    llm_retry_count: int = 3                        # 失败重试次数
    llm_retry_delay: float = 2.0                    # 重试间隔基数（秒）
    llm_token_limit_per_call: int = 6000            # 单次调用输入 Token 上限
    llm_cost_per_1k_input: float = 0.0              # 输入成本（元/1K tokens，0=不计费）
    llm_cost_per_1k_output: float = 0.0             # 输出成本（元/1K tokens）

    # 规则文件路径
    rules_dir: str = "rules"

    # 文件上传限制
    max_file_size_mb: int = 50
    allowed_extensions: list[str] = ["pdf", "docx"]

    # 审计日志
    audit_log_enabled: bool = True
    minio_connect_timeout: int = 5

    # 日志
    log_level: str = "info"

    # 邮件服务 (Resend)
    resend_api_key: str = ""
    email_from_address: str = "noreply@baohegui.com"

    model_config = {"env_prefix": "BHG_", "env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def _validate_secret_key(self) -> "Settings":
        """生产环境必须设置非默认的 secret_key，否则拒绝启动"""
        if not self.debug and self.secret_key == "change-me-in-production":
            raise ValueError(
                "生产环境禁止使用默认 secret_key。"
                "请设置环境变量 BHG_SECRET_KEY 为一个随机字符串。"
                "示例: python -c 'import secrets; print(secrets.token_urlsafe(64))'"
            )
        return self

    def get_cors_origins(self) -> list[str]:
        """将逗号分隔的 CORS_ORIGINS 解析为列表，debug 模式回退为 ['*']"""
        if self.debug:
            return ["*"]
        if not self.cors_origins.strip():
            return []
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
