"""动态策略管理 API — 管理员专用

所有策略状态变更只能通过以下端点完成，禁止直接赋值 DynamicPolicy.status。
写操作 require_admin + 审计日志。
"""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import audit_service
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


def _audit(user_id: int, action: str, resource_id: int, policy: DynamicPolicy,
           from_status: str = "", to_status: str = "", note: str = ""):
    """统一审计写入 — 包含可见字段但不包含完整 policy_data。"""
    policy_fields_hash = hashlib.sha256(
        policy.policy_data.encode("utf-8")
    ).hexdigest()[:16] if policy.policy_data else "none"
    audit_service.log(
        user_id=user_id,
        action=action,
        resource="dynamic_policy",
        resource_id=str(resource_id),
        detail={
            "policy_key": policy.policy_key,
            "policy_type": policy.policy_type,
            "scope_type": policy.scope_type,
            "scope_id": policy.scope_id,
            "from_status": from_status,
            "to_status": to_status,
            "note": note,
            "policy_data_hash": policy_fields_hash,
        },
    )


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
    """创建 draft 策略（管理员）。"""
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
        _audit(int(user["sub"]), "policy_create", policy.id, policy, to_status="draft")
        return _to_response(policy)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{policy_id}/submit")
def submit_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """提交审批: draft → review。"""
    try:
        policy = db.query(DynamicPolicy).filter(DynamicPolicy.id == policy_id).first()
        from_status = policy.status if policy else "draft"
        policy = submit_for_review(db, policy_id, admin_id=int(user["sub"]))
        _audit(int(user["sub"]), "policy_submit", policy.id, policy,
               from_status=from_status, to_status="review")
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
    """审批通过: review → approved。"""
    try:
        policy = db.query(DynamicPolicy).filter(DynamicPolicy.id == policy_id).first()
        from_status = policy.status if policy else "review"
        policy = approve(db, policy_id, admin_id=int(user["sub"]), note=note)
        _audit(int(user["sub"]), "policy_approve", policy.id, policy,
               from_status=from_status, to_status="approved", note=note)
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
    """审批拒绝: review → rejected。"""
    try:
        policy = db.query(DynamicPolicy).filter(DynamicPolicy.id == policy_id).first()
        from_status = policy.status if policy else "review"
        policy = reject(db, policy_id, admin_id=int(user["sub"]), reason=reason)
        _audit(int(user["sub"]), "policy_reject", policy.id, policy,
               from_status=from_status, to_status="rejected", note=reason)
        return _to_response(policy)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{policy_id}/apply")
def apply_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """应用策略: approved → applied（此后影响执行链）。"""
    try:
        policy = db.query(DynamicPolicy).filter(DynamicPolicy.id == policy_id).first()
        from_status = policy.status if policy else "approved"
        policy = apply(db, policy_id, admin_id=int(user["sub"]))
        _audit(int(user["sub"]), "policy_apply", policy.id, policy,
               from_status=from_status, to_status="applied")
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
    """紧急回滚: applied → rolled_back。"""
    try:
        policy = db.query(DynamicPolicy).filter(DynamicPolicy.id == policy_id).first()
        from_status = policy.status if policy else "applied"
        policy = rollback(db, policy_id, admin_id=int(user["sub"]), reason=reason)
        _audit(int(user["sub"]), "policy_rollback", policy.id, policy,
               from_status=from_status, to_status="rolled_back", note=reason)
        return _to_response(policy)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{policy_id}/revise")
def revise_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """修订: rejected → draft。"""
    try:
        policy = db.query(DynamicPolicy).filter(DynamicPolicy.id == policy_id).first()
        from_status = policy.status if policy else "rejected"
        policy = revise(db, policy_id)
        _audit(int(user["sub"]), "policy_revise", policy.id, policy,
               from_status=from_status, to_status="draft")
        return _to_response(policy)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
