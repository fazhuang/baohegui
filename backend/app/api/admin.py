"""管理后台 API — 用户管理 + 审计日志 + 文件对比 + 计费

所有端点需要管理员权限。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import audit_service
from app.core.security import hash_password, require_admin
from app.db.database import get_db, SessionLocal
from app.models.document import ComplianceReport, UploadedFile, DocumentSection
from app.models.user import User
from app.services.usage_tracker import usage_tracker

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ═══════════════════════════════════════════════════════════════
# 请求/响应模型
# ═══════════════════════════════════════════════════════════════

class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    company: str = ""
    email: str = ""


class UpdateUserRequest(BaseModel):
    password: str | None = None
    role: str | None = None
    company: str | None = None
    email: str | None = None
    is_active: bool | None = None


class BillingThreshold(BaseModel):
    max_monthly_tokens: int = 1_000_000       # 月 Token 上限
    max_monthly_cost_yuan: float = 100.0      # 月费用上限（元）
    alert_threshold_pct: float = 80.0         # 告警百分比


# ═══════════════════════════════════════════════════════════════
# 1. 用户管理
# ═══════════════════════════════════════════════════════════════

@router.get("/users")
async def list_users(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """列出所有用户"""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "company": u.company or "",
            "email": u.email or "",
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.post("/users")
async def create_user(
    req: CreateUserRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """管理员创建用户"""
    existing = db.query(User).filter(User.username == req.username).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")

    user = User(
        username=req.username,
        hashed_password=hash_password(req.password),
        role=req.role,
        company=req.company,
        email=req.email,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    audit_service.log(
        user_id=int(admin["sub"]),
        action="create_user",
        resource="user",
        resource_id=str(user.id),
        detail={"username": req.username, "role": req.role},
    )

    return {"message": "用户已创建", "user_id": user.id}


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    req: UpdateUserRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """更新用户信息"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    changes = {}
    if req.password is not None:
        user.hashed_password = hash_password(req.password)
        changes["password"] = True
    if req.role is not None:
        user.role = req.role
        changes["role"] = req.role
    if req.company is not None:
        user.company = req.company
        changes["company"] = req.company
    if req.email is not None:
        user.email = req.email
        changes["email"] = req.email
    if req.is_active is not None:
        user.is_active = req.is_active
        changes["is_active"] = req.is_active

    db.commit()

    audit_service.log(
        user_id=int(admin["sub"]),
        action="update_user",
        resource="user",
        resource_id=str(user.id),
        detail=changes,
    )

    return {"message": "用户已更新"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """删除用户"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if user.id == int(admin["sub"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除自己的账户")

    username = user.username
    db.delete(user)
    db.commit()

    audit_service.log(
        user_id=int(admin["sub"]),
        action="delete_user",
        resource="user",
        resource_id=str(user_id),
        detail={"username": username},
    )

    return {"message": "用户已删除"}


# ═══════════════════════════════════════════════════════════════
# 2. 审计日志
# ═══════════════════════════════════════════════════════════════

@router.get("/audit")
async def list_audit_logs(
    user_id: int | None = Query(None, description="按用户筛选"),
    limit: int = Query(100, ge=1, le=500),
    admin: dict = Depends(require_admin),
):
    """查看审计日志"""
    logs = audit_service.query(user_id=user_id, limit=limit)
    return {
        "total": len(logs),
        "logs": logs,
    }


# ═══════════════════════════════════════════════════════════════
# 3. 文件差异对比
# ═══════════════════════════════════════════════════════════════

@router.get("/compare")
async def compare_files(
    file_a: int = Query(..., description="文件 A 的 db_id"),
    file_b: int = Query(..., description="文件 B 的 db_id"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """对比两个已检查文件的结构差异和合规评分变化"""
    f_a = db.query(UploadedFile).filter(UploadedFile.id == file_a).first()
    f_b = db.query(UploadedFile).filter(UploadedFile.id == file_b).first()
    if not f_a or not f_b:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    # 基本信息
    info = {
        "file_a": {"id": f_a.id, "filename": f_a.filename, "file_size": f_a.file_size,
                   "page_count": f_a.page_count, "file_hash": f_a.file_hash,
                   "status": f_a.status},
        "file_b": {"id": f_b.id, "filename": f_b.filename, "file_size": f_b.file_size,
                   "page_count": f_b.page_count, "file_hash": f_b.file_hash,
                   "status": f_b.status},
    }

    # 哈希比较
    is_same_file = f_a.file_hash == f_b.file_hash
    info["is_same_file"] = is_same_file

    # 章节对比
    sections_a = db.query(DocumentSection).filter(DocumentSection.file_id == file_a).all()
    sections_b = db.query(DocumentSection).filter(DocumentSection.file_id == file_b).all()

    types_a = {s.section_type for s in sections_a}
    types_b = {s.section_type for s in sections_b}
    section_diff = {
        "both": sorted(types_a & types_b),
        "only_in_a": sorted(types_a - types_b),
        "only_in_b": sorted(types_b - types_a),
    }

    # 合规评分对比
    report_a = db.query(ComplianceReport).filter(ComplianceReport.file_id == file_a).order_by(
        ComplianceReport.created_at.desc()).first()
    report_b = db.query(ComplianceReport).filter(ComplianceReport.file_id == file_b).order_by(
        ComplianceReport.created_at.desc()).first()

    score_diff = None
    if report_a and report_b:
        score_diff = {
            "total_score": {"a": report_a.total_score, "b": report_b.total_score,
                            "delta": round(report_b.total_score - report_a.total_score, 1)},
            "section_score": {"a": report_a.section_score, "b": report_b.section_score},
            "keyword_score": {"a": report_a.keyword_score, "b": report_b.keyword_score},
            "forbidden_score": {"a": report_a.forbidden_score, "b": report_b.forbidden_score},
            "semantic_score": {"a": report_a.semantic_score, "b": report_b.semantic_score},
            "violation_count": {"a": report_a.violation_count, "b": report_b.violation_count,
                                "delta": report_b.violation_count - report_a.violation_count},
        }

    return {
        "info": info,
        "section_diff": section_diff,
        "score_diff": score_diff,
    }


# ═══════════════════════════════════════════════════════════════
# 4. 计费与用量
# ═══════════════════════════════════════════════════════════════

# 内存中的计费配置（后续可迁移到 settings / DB）
_billing_config: BillingThreshold = BillingThreshold()


@router.get("/billing/threshold")
async def get_billing_threshold(admin: dict = Depends(require_admin)):
    """获取当前计费阈值配置"""
    return _billing_config.model_dump()


@router.put("/billing/threshold")
async def set_billing_threshold(
    req: BillingThreshold,
    admin: dict = Depends(require_admin),
):
    """更新计费阈值配置"""
    global _billing_config
    _billing_config = req

    audit_service.log(
        user_id=int(admin["sub"]),
        action="update_billing_threshold",
        resource="billing",
        detail=req.model_dump(),
    )

    return {"message": "计费阈值已更新", "config": req.model_dump()}


@router.get("/billing/status")
async def get_billing_status(admin: dict = Depends(require_admin)):
    """获取当前用量与告警状态"""
    stats = usage_tracker.get_stats()
    cfg = _billing_config

    token_pct = (stats.total_tokens / cfg.max_monthly_tokens * 100) if cfg.max_monthly_tokens > 0 else 0.0
    cost_pct = (stats.total_cost_yuan / cfg.max_monthly_cost_yuan * 100) if cfg.max_monthly_cost_yuan > 0 else 0.0

    alerts = []
    if token_pct >= cfg.alert_threshold_pct:
        alerts.append({
            "type": "token_usage",
            "message": f"Token 用量已达 {token_pct:.1f}%（{stats.total_tokens:,} / {cfg.max_monthly_tokens:,}）",
            "severity": "critical" if token_pct >= 100 else "warning",
        })
    if cost_pct >= cfg.alert_threshold_pct:
        alerts.append({
            "type": "cost",
            "message": f"费用已达 {cost_pct:.1f}%（¥{stats.total_cost_yuan:.4f} / ¥{cfg.max_monthly_cost_yuan:.2f}）",
            "severity": "critical" if cost_pct >= 100 else "warning",
        })

    return {
        "current_period": "monthly",
        "tokens": {
            "used": stats.total_tokens,
            "limit": cfg.max_monthly_tokens,
            "pct": round(token_pct, 1),
        },
        "cost": {
            "used_yuan": round(stats.total_cost_yuan, 4),
            "limit_yuan": cfg.max_monthly_cost_yuan,
            "pct": round(cost_pct, 1),
        },
        "calls": {
            "total": stats.total_calls,
            "success_rate": stats.success_rate,
        },
        "alerts": alerts,
    }
