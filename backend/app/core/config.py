"""应用配置管理"""

import os
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

# ── Vercel 环境检测 ────────────────────────────────
# 在 Vercel 上自动使用 SQLite，避免 PostgreSQL + psycopg2 依赖
if os.environ.get("VERCEL") or os.path.exists("/vercel"):
    import shutil

    os.environ.setdefault("BHG_database_url", "sqlite:////tmp/baohegui.db")
    os.environ.setdefault("BHG_debug", "true")
    os.environ.setdefault("BHG_cors_origins", "*")
    os.environ.setdefault("BHG_llm_mock_mode", "true")
    os.environ.setdefault("BHG_minio_endpoint", "0.0.0.0:1")
    os.environ.setdefault("BHG_log_level", "warning")
    # 规则文件目录：复制到 /tmp/ 以便写入版本目录
    src = Path(__file__).resolve().parent.parent.parent / "rules"
    dst = Path("/tmp/rules")
    if src.exists() and not dst.exists():
        try:
            shutil.copytree(src, dst)
        except Exception:
            pass
    os.environ.setdefault("BHG_rules_dir", "/tmp/rules")


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
    llm_api_key: str = ""  # API 密钥（Ollama 可不填）
    llm_model: str = "qwen2.5:14b"  # 模型名称
    llm_max_tokens: int = 4096  # 单次最大生成 Token
    llm_temperature: float = 0.1  # 生成温度（合规审查用低温）
    llm_timeout: int = 120  # API 超时（秒）
    llm_mock_mode: bool = False  # 是否使用 mock（开发用，生产环境必须为 False）
    llm_retry_count: int = 3  # 失败重试次数
    llm_retry_delay: float = 2.0  # 重试间隔基数（秒）
    llm_token_limit_per_call: int = 6000  # 单次调用输入 Token 上限
    llm_cost_per_1k_input: float = 0.0  # 输入成本（元/1K tokens，0=不计费）
    llm_cost_per_1k_output: float = 0.0  # 输出成本（元/1K tokens）

    # 规则文件路径
    rules_dir: str = "rules"

    # 多模型路由
    llm_multi_model_enabled: bool = False  # 是否启用多模型路由
    llm_multi_model_config: str = "rules/prompts/model_routing.json"
    # 各模型API密钥
    llm_deepseek_api_key: str = ""
    llm_qwen_api_key: str = ""

    # 语义切割（Semantic Chunking）
    semantic_chunking_enabled: bool = True  # 是否启用语义切割
    section_affinity_path: str = "rules/section_affinity.json"  # 章节关联矩阵路径
    chunk_overlap_ratio: float = 0.15  # chunk 间重叠比例（0=无重叠）
    chunk_overlap_min_tokens: int = 200  # 最小重叠 Token 数
    chunk_overlap_max_tokens: int = 800  # 最大重叠 Token 数
    chunk_auto_degrade_threshold: int = 5  # 章节数 ≤ 此值时回退到顺序拼接

    # 文件上传限制
    max_file_size_mb: int = 50
    allowed_extensions: list[str] = ["pdf", "docx"]

    # 零Token路由审查阈值
    routing_green_budget_max: float = 1_000_000  # 绿灯：预算≤100万
    routing_yellow_budget_max: float = 5_000_000  # 黄灯：预算≤500万
    routing_red_methods: list[str] = ["单一来源", "竞争性谈判"]  # 红灯采购方式
    routing_yellow_methods: list[str] = ["邀请招标", "竞争性磋商"]  # 黄灯采购方式

    # 审计日志
    audit_log_enabled: bool = True
    minio_connect_timeout: int = 5  # MinIO 超时（秒）

    # 案例采集
    case_scrape_enabled: bool = True
    case_scrape_interval_hours: int = 168  # 每周一次
    ccgp_base_url: str = "https://www.ccgp.gov.cn"

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
