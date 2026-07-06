"""动态策略管理 API — 管理员专用

所有策略状态变更只能通过以下端点完成，禁止直接赋值 DynamicPolicy.status。
写操作 require_admin。
审计日志已在 policy_repository 中与策略状态变更原子写入。
API 仅负责认证、参数绑定和错误映射。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_admin
from app.db.database import get_db
from app.services.policy_repository import (
    DynamicPolicy,
    create_draft,
    submit_for_review,
    approve,
    reject,
    apply,
    rollback,
    revise,
)

router = APIRouter(prefix="/api/admin/policies", tags=["admin-policies"])


class CreatePolicyRequest(BaseModel):
    policy_key: str
    policy_type: str = "tenant"
    policy_data: str  # JSON string
    scope_type: str
    scope_id: str
    description: str | None = None


class PolicyResponse(BaseModel):
    id: int
    policy_key: str
    policy_type: str
    status: str
    scope_type: str
    scope_id: str
    created_by: int | None
    description: str | None
    approved_by: int | None
    applied_by: int | None
    created_at: str | None


def _to_response(p: DynamicPolicy) -> dict:
    return PolicyResponse(
        id=p.id,
        policy_key=p.policy_key,
        policy_type=p.policy_type,
        status=p.status,
        scope_type=p.scope_type,
        scope_id=p.scope_id,
        created_by=p.created_by,
        description=p.description,
        approved_by=p.approved_by,
        applied_by=p.applied_by,
        created_at=p.created_at.isoformat() if p.created_at else None,
    ).model_dump()


@router.get("/")
def list_policies(
    status_filter: str | None = Query(default=None, alias="status"),
    scope_type: str | None = None,
    scope_id: str | None = None,
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """列出动态策略（管理员）。"""
    q = db.query(DynamicPolicy)
    if status_filter:
        q = q.filter(DynamicPolicy.status == status_filter)
    if scope_type:
        q = q.filter(DynamicPolicy.scope_type == scope_type)
    if scope_id:
        q = q.filter(DynamicPolicy.scope_id == scope_id)
    policies = q.order_by(DynamicPolicy.created_at.desc()).limit(100).all()
    return {"policies": [_to_response(p) for p in policies]}


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_policy(
    req: CreatePolicyRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """创建 draft 策略（管理员）。审计在 repository 中原子写入。"""
    try:
        policy = create_draft(
            db=db,
            policy_key=req.policy_key,
            policy_type=req.policy_type,
            policy_data=req.policy_data,
            scope_type=req.scope_type,
            scope_id=req.scope_id,
            created_by=int(user["sub"]),
            description=req.description,
        )
        return _to_response(policy)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{policy_id}/submit")
def submit_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """提交审批: draft → review。审计在 repository 中原子写入。"""
    try:
        policy = submit_for_review(db, policy_id, admin_id=int(user["sub"]))
        return _to_response(policy)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{policy_id}/approve")
def approve_policy(
    policy_id: int,
    note: str = Query(default=""),
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """审批通过: review → approved。审计在 repository 中原子写入。"""
    try:
        policy = approve(db, policy_id, admin_id=int(user["sub"]), note=note)
        return _to_response(policy)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{policy_id}/reject")
def reject_policy(
    policy_id: int,
    reason: str = Query(default=""),
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """审批拒绝: review → rejected。审计在 repository 中原子写入。"""
    try:
        policy = reject(db, policy_id, admin_id=int(user["sub"]), reason=reason)
        return _to_response(policy)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{policy_id}/apply")
def apply_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """应用策略: approved → applied（此后影响执行链）。审计在 repository 中原子写入。"""
    try:
        policy = apply(db, policy_id, admin_id=int(user["sub"]))
        return _to_response(policy)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{policy_id}/rollback")
def rollback_policy(
    policy_id: int,
    reason: str = Query(default=""),
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """紧急回滚: applied → rolled_back。审计在 repository 中原子写入。"""
    try:
        policy = rollback(db, policy_id, admin_id=int(user["sub"]), reason=reason)
        return _to_response(policy)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{policy_id}/revise")
def revise_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """修订: rejected → draft。审计在 repository 中原子写入。"""
    try:
        policy = revise(db, policy_id, admin_id=int(user["sub"]))
        return _to_response(policy)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
