"""包合规 - 后端入口"""

import logging
import time
import traceback
from collections import defaultdict
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import admin, announcements, auth, categories, check, crawler, knowledge_graph, member, report, rules, stats, upload
from app.core.config import settings
from app.core.metrics import (
    http_request_duration_seconds,
    http_requests_total,
    get_metrics_response,
    rules_loaded_gauge,
)

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
# 安全中间件
# ═══════════════════════════════════════════════════════════════


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """为所有响应添加安全头

    CSP 说明:
    - 'unsafe-inline' / 'unsafe-eval' 是妥协：Vite/React/Ant Design 在生产构建中仍需
      style-src 'unsafe-inline'（Ant Design 动态注入样式），且 Webpack/Vite HMR 需
      script-src 'unsafe-eval'（仅 dev）。生产环境建议启用 nonce 或 hash-based CSP。
    - 当前 CSP 作为第一道防线已覆盖 XSS 主攻击面（object-src 'none', base-uri 'self',
      frame-ancestors 'none' 均已严格设置）。
    - TODO: 为非 dev 构建启用 nonce-based script-src + style-src。
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # debug 模式下放宽 CSP 以支持 Vite HMR；生产环境收紧
        if settings.debug:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; "
                "connect-src 'self' https: ws:; "
                "font-src 'self'; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "form-action 'self'; "
                "frame-ancestors 'none';"
            )
        else:
            # 生产 CSP：仅保留 style-src 'unsafe-inline' (Ant Design 静态提取路径最小化需求)
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; "
                "connect-src 'self' https:; "
                "font-src 'self'; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "form-action 'self'; "
                "frame-ancestors 'none';"
            )
        # HSTS: 仅 HTTPS / 生产环境启用
        if not settings.debug:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        return response


class TrustedHostMiddleware(BaseHTTPMiddleware):
    """校验 Host 请求头，拒绝未知主机以防止 DNS rebinding。

    信任主机列表：
    - CORS origins 中的域名
    - localhost / 127.0.0.1
    - Railway / Vercel 部署域名
    - 环境变量 BHG_TRUSTED_HOSTS 中指定的域名（逗号分隔）

    debug 模式下此中间件跳过校验。
    """

    _trusted_hosts: set[str] | None = None

    def _get_trusted_hosts(self) -> set[str]:
        if self._trusted_hosts is not None:
            return self._trusted_hosts
        hosts: set[str] = {"localhost", "127.0.0.1"}
        # 从 CORS origins 提取域名
        for origin in settings.get_cors_origins():
            if origin == "*":
                continue
            try:
                parsed = urlparse(origin if "://" in origin else f"https://{origin}")
                if parsed.hostname:
                    hosts.add(parsed.hostname)
            except Exception:
                pass
        # 从环境变量读取
        import os
        env_hosts = os.environ.get("BHG_TRUSTED_HOSTS", "")
        if env_hosts:
            for h in env_hosts.split(","):
                h = h.strip()
                if h:
                    hosts.add(h)
        # Railway/Vercel 域名段
        hosts.update({
            ".railway.app", ".railway.internal", ".up.railway.app",
            ".vercel.app", ".now.sh",
        })
        self._trusted_hosts = hosts
        return hosts

    def _host_allowed(self, host: str) -> bool:
        """检查 Host 头是否被信任"""
        if not host:
            return False
        host = host.split(":")[0].lower()  # remove port
        trusted = self._get_trusted_hosts()
        if host in trusted:
            return True
        # 通配符匹配 (.railway.app 匹配 anything.railway.app)
        for t in trusted:
            if t.startswith(".") and host.endswith(t):
                return True
        return False

    async def dispatch(self, request: Request, call_next):
        # debug 模式跳过
        if settings.debug:
            return await call_next(request)
        host = request.headers.get("host", "")
        if not self._host_allowed(host):
            logger.warning("TrustedHostMiddleware: 拒绝未知 Host: %s", host)
            return JSONResponse(
                status_code=421,
                content={"detail": "无效的请求主机"},
            )
        return await call_next(request)


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


# 生产环境关闭 API 文档
_docs_enabled = settings.debug
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="招标文件发布前合规自检系统" if _docs_enabled else None,
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
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

# 安全中间件
app.add_middleware(TrustedHostMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


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


# ── Prometheus HTTP 指标中间件 ─────────────────────────────


@app.middleware("http")
async def prometheus_metrics_middleware(request: Request, call_next):
    """记录每个 HTTP 请求的计数与耗时"""
    start = time.monotonic()
    response = await call_next(request)
    duration = time.monotonic() - start
    # 简化 endpoint 标签：取路径前缀（避免高基数）
    path = request.url.path
    endpoint = _simplify_path(path)
    http_requests_total.labels(
        method=request.method,
        endpoint=endpoint,
        status_code=str(response.status_code),
    ).inc()
    http_request_duration_seconds.labels(
        method=request.method,
        endpoint=endpoint,
    ).observe(duration)
    return response


def _simplify_path(path: str) -> str:
    """将带 ID 的路径简化为模式（如 /api/report/42 → /api/report/{id}）"""
    import re
    # 替换数字段
    path = re.sub(r"/\d+", "/{id}", path)
    # 替换 UUID 段
    path = re.sub(r"/[0-9a-fA-F-]{36}", "/{uuid}", path)
    return path


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
app.include_router(categories.router)
app.include_router(knowledge_graph.router)
app.include_router(crawler.router)


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
    # 刷新规则引擎指标
    from app.engine.rule_engine import rule_engine
    rules_loaded_gauge.set(len(rule_engine.rules))
    return {"status": "ok", "version": settings.app_version}


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus 指标导出端点"""
    return PlainTextResponse(content=get_metrics_response(), media_type="text/plain; version=0.0.4")
