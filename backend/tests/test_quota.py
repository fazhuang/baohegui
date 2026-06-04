"""配额管理集成测试 — 配额创建、消耗、耗尽"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.models.subscription import UserQuota, PLAN_QUOTAS
from app.services.quota_service import (
    get_or_create_quota,
    check_quota,
    consume_file,
    _get_period_key,
)


class TestQuotaCreation:
    """配额创建测试"""

    def test_new_user_auto_free_plan(self, db_session: Session):
        """新用户自动获得免费配额"""
        quota = get_or_create_quota(db_session, user_id=100, plan="free")

        assert quota.user_id == 100
        assert quota.plan == "free"
        assert quota.files_limit == PLAN_QUOTAS["free"]["files_limit"]  # 5
        assert quota.files_used == 0
        assert quota.tokens_used == 0
        assert quota.cost_used_yuan == 0.0

    def test_pro_plan_quota(self, db_session: Session):
        """Pro 计划配额值正确"""
        quota = get_or_create_quota(db_session, user_id=200, plan="pro")

        assert quota.plan == "pro"
        assert quota.files_limit == PLAN_QUOTAS["pro"]["files_limit"]  # 100
        assert quota.tokens_limit == PLAN_QUOTAS["pro"]["tokens_limit"]

    def test_quota_same_period_singleton(self, db_session: Session):
        """同一用户同一月度只应有一条配额记录"""
        q1 = get_or_create_quota(db_session, user_id=300, plan="free")
        q2 = get_or_create_quota(db_session, user_id=300, plan="free")

        assert q1.id == q2.id
        assert q1.period_key == q2.period_key

    def test_period_key_format(self):
        """period_key 格式应为 YYYY-MM"""
        key = _get_period_key()
        import re
        assert re.match(r"^\d{4}-\d{2}$", key), f"Invalid period_key: {key}"


class TestQuotaConsumption:
    """配额消耗测试"""

    def test_consume_file_increases_used(self, db_session: Session):
        """文件上传后 files_used 增加"""
        quota = get_or_create_quota(db_session, user_id=400, plan="free")
        assert quota.files_used == 0

        result = consume_file(db_session, user_id=400)
        assert result is True

        # 刷新以查看更新后的值
        db_session.refresh(quota)
        assert quota.files_used == 1

    def test_consume_multiple_files(self, db_session: Session):
        """多次消耗正确递增"""
        get_or_create_quota(db_session, user_id=500, plan="free")

        for i in range(3):
            result = consume_file(db_session, user_id=500)
            assert result is True

        quota = get_or_create_quota(db_session, user_id=500)
        assert quota.files_used == 3

    def test_check_quota_reflects_usage(self, db_session: Session):
        """check_quota 反映当前使用情况"""
        get_or_create_quota(db_session, user_id=600, plan="free")

        # 初始状态
        status = check_quota(db_session, user_id=600)
        assert status["can_upload"] is True
        assert status["files_remaining"] == 5
        assert status["exhausted"] is False

        # 消耗 2 次
        consume_file(db_session, user_id=600)
        consume_file(db_session, user_id=600)

        status = check_quota(db_session, user_id=600)
        assert status["files_remaining"] == 3
        assert status["files_used"] == 2


class TestQuotaExhaustion:
    """配额耗尽测试"""

    def test_exhausted_prevent_upload(self, db_session: Session):
        """超过限制后 should_upload/exhausted 为 True"""
        quota = get_or_create_quota(db_session, user_id=700, plan="free")
        quota.files_used = quota.files_limit  # 直接设为满

        # consume_file 应返回 False
        result = consume_file(db_session, user_id=700)
        assert result is False

        # check_quota 应标记 exhausted
        status = check_quota(db_session, user_id=700)
        assert status["exhausted"] is True
        assert status["can_upload"] is False
        assert status["files_remaining"] == 0

    def test_exhausted_boundary(self, db_session: Session):
        """边界：刚好用完最后一份配额"""
        quota = get_or_create_quota(db_session, user_id=800, plan="free")
        quota.files_used = quota.files_limit - 1  # 4/5

        # 最后一次成功
        result = consume_file(db_session, user_id=800)
        assert result is True

        # 再次尝试失败
        result = consume_file(db_session, user_id=800)
        assert result is False

    def test_quota_reset_new_period(self, db_session: Session):
        """新月份应创建新配额（period_key 不同）"""
        # 模拟旧月份的配额
        old_quota = UserQuota(
            user_id=900,
            plan="free",
            period_key="2020-01",
            files_limit=5,
            files_used=5,  # 已用完
        )
        db_session.add(old_quota)
        db_session.commit()

        # 当前月份应创建新的配额记录
        new_quota = get_or_create_quota(db_session, user_id=900, plan="free")
        assert new_quota.id != old_quota.id
        assert new_quota.period_key == _get_period_key()
        assert new_quota.files_used == 0  # 新月份重新开始
