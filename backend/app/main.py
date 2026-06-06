"""包合规 - 后端入口"""

import logging
import time
import traceback
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, announcements, auth, check, knowledge_graph, member, report, rules, stats, upload
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 简单频率限制（内存）
# ═══════════════════════════════════════════════════════════════

_rate_window: int = 60  # 窗口秒数
_rate_limits: dict[str, list[float]] = defaultdict(list)

RATE_LIMITS = {
    "/api/auth/login": 10,  # 登录: 10次/分钟
    "/api/auth/register": 5,  # 注册: 5次/分钟
    "/api/upload/": 20,  # 上传: 20次/分钟
    "/api/check/": 30,  # 检查: 30次/分钟
}


def _check_rate_limit(path: str) -> tuple[bool, int]:
    """检查路径是否超频。返回 (allowed, remaining)"""
    limit = RATE_LIMITS.get(path)
    if limit is None:
        # 模糊匹配前缀
        for prefix, lmt in RATE_LIMITS.items():
            if path.startswith(prefix):
                limit = lmt
                break
    if limit is None:
        return True, 999

    now = time.time()
    cutoff = now - _rate_window
    _rate_limits[path] = [t for t in _rate_limits[path] if t > cutoff]

    if len(_rate_limits[path]) >= limit:
        return False, 0

    _rate_limits[path].append(now)
    return True, limit - len(_rate_limits[path])


# ═══════════════════════════════════════════════════════════════
# 应用生命周期
# ═══════════════════════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"{settings.app_name} v{settings.app_version} 启动中...")

    # 1. 初始化数据库表
    try:
        from app.db.database import init_db

        init_db()
        logger.info("数据库表初始化完成")
    except Exception as e:
        logger.error("数据库初始化失败: %s", e)

    # 2. 初始化 MinIO bucket
    try:
        from app.services.minio_service import minio_service

        minio_service.ensure_bucket()
    except Exception as e:
        logger.warning("MinIO bucket 初始化失败（非致命）: %s", e)

    # 3. 启动规则同步调度器（后台任务）
    try:
        from app.services.sync_scheduler import sync_scheduler

        await sync_scheduler.start()
    except Exception as e:
        logger.warning("同步调度器启动失败（非致命）: %s", e)

    yield

    # 关闭
    try:
        from app.services.sync_scheduler import sync_scheduler

        await sync_scheduler.stop()
    except Exception:
        pass
    logger.info("应用关闭")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="招标文件发布前合规自检系统",
    lifespan=lifespan,
)

# CORS 配置
# debug 模式下允许所有来源；生产模式从 BHG_CORS_ORIGINS 环境变量读取
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)


# ── 频率限制中间件 ────────────────────────────────────────


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    allowed, remaining = _check_rate_limit(path)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "请求过于频繁，请稍后再试"},
            headers={"Retry-After": str(_rate_window)},
        )
    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response


# 注册路由
app.include_router(upload.router)
app.include_router(check.router)
app.include_router(report.router)
app.include_router(auth.router)
app.include_router(rules.router)
app.include_router(stats.router)
app.include_router(admin.router)
app.include_router(member.router)
app.include_router(announcements.router)
app.include_router(knowledge_graph.router)


# ═══════════════════════════════════════════════════════════════
# 全局异常处理器
# ═══════════════════════════════════════════════════════════════


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """HTTPException 保持原样透传"""
    logger.warning(
        "HTTP %d on %s %s: %s",
        exc.status_code,
        request.method,
        request.url.path,
        exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """全局未捕获异常处理

    - 生产模式（debug=False）：返回通用错误消息，不暴露内部信息
    - 开发模式（debug=True）：返回详细 traceback
    """
    logger.error(
        "未处理的异常 on %s %s: %s\n%s",
        request.method,
        request.url.path,
        str(exc),
        traceback.format_exc(),
    )

    if settings.debug:
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"服务器内部错误: {str(exc)}",
                "type": type(exc).__name__,
                "traceback": traceback.format_exc().split("\n"),
            },
        )
    else:
        return JSONResponse(
            status_code=500,
            content={"detail": "服务器内部错误，请稍后重试"},
        )


@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.app_version}
