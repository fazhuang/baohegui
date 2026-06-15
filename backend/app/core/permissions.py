"""统一权限服务（RBAC）

中央化的权限校验逻辑，替代散落在各路由处理器中的内联检查。

设计原则：
- 权限是枚举值，不直接与角色绑定（方便后续扩展自定义角色）
- 每个 FastAPI 依赖注入返回一个布尔/403 错误
- 角色 → 权限映射集中声明
"""

from __future__ import annotations

from enum import Enum
from typing import Callable

from fastapi import Depends, HTTPException, status

from .security import get_current_user


class Permission(str, Enum):
    """权限枚举 — 资源:操作 格式"""

    # ── 文件操作 ──
    FILE_UPLOAD = "file:upload"
    FILE_CHECK = "file:check"

    # ── 报告操作 ──
    REPORT_VIEW = "report:view"
    REPORT_DOWNLOAD = "report:download"
    REPORT_LIST_ALL = "report:list_all"

    # ── 规则管理 ──
    RULES_READ = "rules:read"
    RULES_WRITE = "rules:write"
    RULES_SYNC = "rules:sync"

    # ── 管理后台 ──
    ADMIN_USERS = "admin:users"
    ADMIN_AUDIT = "admin:audit"
    ADMIN_BILLING = "admin:billing"

    # ── 系统统计 ──
    STATS_DASHBOARD = "stats:dashboard"

    # ── 知识图谱 ──
    KG_READ = "kg:read"
    KG_SEED = "kg:seed"

    # ── 爬虫 ──
    CRAWLER_READ = "crawler:read"
    CRAWLER_TRIGGER = "crawler:trigger"


# ═══════════════════════════════════════════════════════════════
# 角色 → 权限映射
# ═══════════════════════════════════════════════════════════════

ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "user": {
        Permission.FILE_UPLOAD,
        Permission.FILE_CHECK,
        Permission.REPORT_VIEW,
        Permission.REPORT_DOWNLOAD,
        Permission.RULES_READ,
        Permission.KG_READ,
        Permission.CRAWLER_READ,
    },
    "admin": set(Permission),  # 管理员拥有全部权限
}


# ═══════════════════════════════════════════════════════════════
# PermissionService
# ═══════════════════════════════════════════════════════════════


class PermissionService:
    """统一权限服务"""

    @staticmethod
    def get_permissions(role: str) -> set[Permission]:
        """返回某个角色拥有的权限集合"""
        if role == "admin":
            return set(Permission)
        return ROLE_PERMISSIONS.get(role, set())

    @staticmethod
    def has_permission(role: str, permission: Permission) -> bool:
        """检查角色是否拥有指定权限"""
        if role == "admin":
            return True
        return permission in ROLE_PERMISSIONS.get(role, set())

    @classmethod
    def require_permission(cls, permission: Permission) -> Callable:
        """FastAPI 依赖注入：要求当前用户拥有指定权限，否则 403。

        用法::

            @router.get("/admin/dashboard")
            async def dashboard(
                user: dict = Depends(PermissionService.require_permission(Permission.STATS_DASHBOARD)),
            ):
                ...
        """

        async def _check(current_user: dict = Depends(get_current_user)) -> dict:
            role = current_user.get("role", "user")
            if not cls.has_permission(role, permission):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"需要权限: {permission.value}",
                )
            return current_user

        return _check

    @classmethod
    async def get_current_user_with_perms(
        cls,
        current_user: dict = Depends(get_current_user),
    ) -> dict:
        """增强版 get_current_user，附带 computed permissions 列表"""
        role = current_user.get("role", "user")
        perms = cls.get_permissions(role)
        current_user["_permissions"] = [p.value for p in perms]
        return current_user


permission_service = PermissionService()
