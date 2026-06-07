"""认证 API — 登录 / 用户信息 / 邮箱验证 / 密码重置"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    verify_password,
    hash_password,
    get_current_user,
)
from app.db.database import get_db
from app.models.user import User
from app.services.email_service import send_verification_email, send_password_reset_email

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── 请求/响应模型 ────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    role: str
    company: str = ""


class UserInfo(BaseModel):
    user_id: int
    username: str
    role: str
    company: str = ""
    email: str = ""


class RegisterRequest(BaseModel):
    username: str
    password: str
    company: str = ""
    email: str = ""


class SendVerificationRequest(BaseModel):
    email: str


class VerifyEmailRequest(BaseModel):
    email: str
    code: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# ── 初始化默认用户 ────────────────────────────────────────────

def _ensure_default_admin(db: Session) -> None:
    """确保数据库中存在默认管理员用户（开发环境用）"""
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        admin = User(
            username="admin",
            hashed_password=hash_password("admin123"),
            role="admin",
            company="包合规开发团队",
            email="admin@baohegui.dev",
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

    # 确保有普通测试用户
    test = db.query(User).filter(User.username == "user").first()
    if not test:
        test = User(
            username="user",
            hashed_password=hash_password("user123"),
            role="user",
            company="测试单位",
        )
        db.add(test)
        db.commit()


# ── 登录 ──────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db: Session = Depends(get_db),
):
    """用户登录，返回 JWT token"""

    # 初始化默认用户（首次启动时）
    try:
        _ensure_default_admin(db)
    except Exception:
        db.rollback()  # 避免 PostgreSQL session 进入 aborted 状态

    # 查询用户
    user = db.query(User).filter(User.username == request.username).first()

    if not user or not verify_password(request.password, user.hashed_password):
        # 开发环境降级：允许 admin/admin123 直接登录
        if request.username == "admin" and request.password == "admin123":
            token = create_access_token(user_id=1, role="admin")
            return LoginResponse(
                access_token=token,
                user_id=1,
                username="admin",
                role="admin",
                company="包合规开发团队",
            )
        if request.username == "user" and request.password == "user123":
            token = create_access_token(user_id=2, role="user")
            return LoginResponse(
                access_token=token,
                user_id=2,
                username="user",
                role="user",
                company="测试单位",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被停用",
        )

    token = create_access_token(user_id=user.id, role=user.role)
    return LoginResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
        role=user.role,
        company=user.company or "",
    )


# ── 用户注册 ──────────────────────────────────────────────────

@router.post("/register", response_model=LoginResponse)
async def register(
    request: RegisterRequest,
    db: Session = Depends(get_db),
):
    """用户注册，自动创建账号并返回 JWT token"""
    # 检查用户名是否已存在
    existing = db.query(User).filter(User.username == request.username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        )

    user = User(
        username=request.username,
        hashed_password=hash_password(request.password),
        role="user",
        company=request.company or "",
        email=request.email or "",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user_id=user.id, role=user.role)
    return LoginResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
        role=user.role,
        company=user.company or "",
    )


# ── 邮箱验证 ──────────────────────────────────────────────────

@router.post("/send-verification")
async def send_verification(
    request: SendVerificationRequest,
    db: Session = Depends(get_db),
):
    """发送邮箱验证码"""
    user = db.query(User).filter(User.email == request.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该邮箱未注册",
        )
    if user.email_verified:
        return {"message": "邮箱已验证，无需重复验证", "verified": True}

    code, _ = await send_verification_email(request.email)
    user.verification_code = code
    user.verification_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.commit()

    return {"message": "验证码已发送", "verified": False}


@router.post("/verify-email")
async def verify_email(
    request: VerifyEmailRequest,
    db: Session = Depends(get_db),
):
    """验证邮箱"""
    user = db.query(User).filter(User.email == request.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    if user.email_verified:
        return {"message": "邮箱已验证", "verified": True}

    if not user.verification_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先发送验证码")

    if user.verification_code_expires_at and datetime.now(timezone.utc) > user.verification_code_expires_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码已过期，请重新发送")

    if user.verification_code != request.code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误")

    user.email_verified = True
    user.verification_code = None
    user.verification_code_expires_at = None
    db.commit()

    return {"message": "邮箱验证成功", "verified": True}


# ── 密码重置 ──────────────────────────────────────────────────

@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    """发送密码重置邮件"""
    user = db.query(User).filter(User.email == request.email).first()
    # 无论用户是否存在，都返回相同提示（防止邮箱枚举）
    if not user:
        return {"message": "如果该邮箱已注册，重置邮件已发送"}

    token, _ = await send_password_reset_email(request.email)
    user.password_reset_token = token
    user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    db.commit()

    return {"message": "如果该邮箱已注册，重置邮件已发送"}


@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """使用重置令牌修改密码"""
    user = db.query(User).filter(User.password_reset_token == request.token).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的重置链接")

    if user.password_reset_expires_at and datetime.now(timezone.utc) > user.password_reset_expires_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="重置链接已过期")

    user.hashed_password = hash_password(request.new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    db.commit()

    return {"message": "密码重置成功，请使用新密码登录"}


# ── 当前用户信息 ──────────────────────────────────────────────

@router.get("/me", response_model=UserInfo)
async def get_me(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前登录用户信息"""
    user_id = int(current_user.get("sub", 0))
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        # token 有效但用户已被删除 → 返回 token 中的信息
        return UserInfo(
            user_id=user_id,
            username=current_user.get("sub", "unknown"),
            role=current_user.get("role", "user"),
        )

    return UserInfo(
        user_id=user.id,
        username=user.username,
        role=user.role,
        company=user.company or "",
        email=user.email or "",
    )
