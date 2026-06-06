"""Vercel Serverless Function 入口"""

import logging
import os

# ── 强制设置 Vercel 环境变量 ──────────────────────
# 注意：pydantic-settings 默认用字段名小写匹配，所以用大写会失效
os.environ["BHG_database_url"] = "sqlite:////tmp/baohegui.db"
os.environ["BHG_debug"] = "true"
os.environ["BHG_cors_origins"] = "*"
os.environ["BHG_secret_key"] = os.urandom(64).hex()
os.environ["BHG_llm_mock_mode"] = "true"
os.environ["BHG_minio_endpoint"] = "0.0.0.0:1"
os.environ["BHG_log_level"] = "warning"

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("vercel")

# ── 导入 FastAPI 应用 ───────────────────────────────────
from sqlalchemy import inspect  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402

# ── 首次请求时初始化默认用户 ──────────────────────────
_seeded = False
_ADMIN_PASSWORD = os.environ.get("BHG_ADMIN_PASSWORD", "")


@app.middleware("http")
async def _seed_on_first_request(request, call_next):
    global _seeded
    if not _seeded:
        try:
            db = SessionLocal()
            try:
                inspector = inspect(db.bind)
                if "users" not in inspector.get_table_names():
                    pass
                elif not db.query(User).first():
                    if _ADMIN_PASSWORD:
                        admin = User(
                            username="admin",
                            hashed_password=hash_password(_ADMIN_PASSWORD),
                            role="admin",
                            company="包合规管理",
                        )
                        db.add(admin)
                        db.commit()
                        logger.info("默认管理员用户已创建 (admin)")
                    else:
                        logger.info("未设置 BHG_ADMIN_PASSWORD，跳过管理员自动创建")
            finally:
                db.close()
        except Exception as e:
            logger.warning("默认用户种子化失败（非致命）: %s", e)
        _seeded = True
    response = await call_next(request)
    return response
