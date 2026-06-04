"""配额服务 — 检查 + 消耗 + 月度重置"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.subscription import PLAN_QUOTAS, UserQuota

logger = logging.getLogger(__name__)


def _get_period_key() -> str:
    """返回当前月度标识，如 "2026-06" """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def get_or_create_quota(db: Session, user_id: int, plan: str = "free") -> UserQuota:
    """获取或创建用户当月配额"""
    period = _get_period_key()
    quota = (
        db.query(UserQuota)
        .filter(UserQuota.user_id == user_id, UserQuota.period_key == period)
        .first()
    )
    if quota is None:
        plan_config = PLAN_QUOTAS.get(plan, PLAN_QUOTAS["free"])
        quota = UserQuota(
            user_id=user_id,
            plan=plan,
            period_key=period,
            files_limit=plan_config["files_limit"],
            tokens_limit=plan_config["tokens_limit"],
            cost_limit_yuan=plan_config["cost_limit_yuan"],
        )
        db.add(quota)
        db.commit()
        db.refresh(quota)
        logger.info("用户 %d 创建 %s 配额: period=%s files=%d tokens=%d",
                    user_id, plan, period, quota.files_limit, quota.tokens_limit)
    return quota


def check_quota(db: Session, user_id: int) -> dict:
    """
    检查用户配额状态。

    Returns:
        {"can_upload": bool, "files_remaining": int, "files_limit": int,
         "tokens_remaining": int, "tokens_limit": int,
         "plan": str, "exhausted": bool}
    """
    quota = get_or_create_quota(db, user_id)

    files_remaining = max(0, quota.files_limit - quota.files_used)
    tokens_remaining = max(0, quota.tokens_limit - quota.tokens_used)
    exhausted = files_remaining <= 0 or tokens_remaining <= 0

    return {
        "can_upload": not exhausted,
        "files_remaining": files_remaining,
        "files_limit": quota.files_limit,
        "files_used": quota.files_used,
        "tokens_remaining": tokens_remaining,
        "tokens_limit": quota.tokens_limit,
        "plan": quota.plan,
        "exhausted": exhausted,
    }


def consume_file(db: Session, user_id: int) -> bool:
    """
    消耗一次文件配额。

    Returns:
        True 表示消耗成功，False 表示配额已用完
    """
    quota = get_or_create_quota(db, user_id)

    if quota.files_used >= quota.files_limit:
        return False

    quota.files_used += 1
    quota.updated_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("用户 %d 消耗文件配额: %d/%d", user_id, quota.files_used, quota.files_limit)
    return True


def consume_tokens(db: Session, user_id: int, tokens: int, cost_yuan: float = 0.0) -> bool:
    """
    消耗 Token 配额。

    Returns:
        True 表示消耗成功，False 表示配额已用完
    """
    quota = get_or_create_quota(db, user_id)

    if quota.tokens_used >= quota.tokens_limit:
        return False

    quota.tokens_used += tokens
    quota.cost_used_yuan += cost_yuan
    quota.updated_at = datetime.now(timezone.utc)
    db.commit()
    return True
