"""认证与权限管理"""

import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .config import settings

security_scheme = HTTPBearer()

# ── bcrypt 兼容性封装（bcrypt 5.x 不兼容 passlib）────


def hash_password(password: str) -> str:
    """使用 bcrypt 直接哈希密码，返回存储格式的字符串"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码是否匹配 bcrypt 哈希"""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: int, role: str = "user") -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭据",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
) -> dict:
    return decode_token(credentials.credentials)


async def require_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """要求管理员角色，否则 403"""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user


# ═══════════════════════════════════════════════════════════════
# 统一资源访问守卫
# ═══════════════════════════════════════════════════════════════


def assert_resource_access(
    db: Session,
    resource: object,
    current_user: dict,
    owner_attr: str = "user_id",
) -> None:
    """统一资源访问守卫：确保当前用户是资源所有者或管理员。

    用法::

        db_report = db.query(ReportModel).filter(ReportModel.id == report_id).first()
        if not db_report:
            raise HTTPException(status_code=404, detail="报告不存在")
        assert_resource_access(db, db_report, user)

    规则：
    - 管理员 (role == 'admin')：通过
    - 所有者 (resource.{owner_attr} == user_id)：通过
    - 其他人：403

    注意：调用方负责先检查资源是否存在，返回 404 后再返回 403 防止信息泄漏。
    如果资源不存在，应返回 404；只有当资源存在且属于他人时，返回 403。
    """
    user_id = int(current_user["sub"])
    role = current_user.get("role", "user")

    if role == "admin":
        return

    owner_id = getattr(resource, owner_attr, None)
    if owner_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此资源",
        )

    if int(owner_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此资源",
        )


def get_current_user_id(current_user: dict) -> int:
    """安全地从 token 字典中提取 user_id"""
    return int(current_user["sub"])
