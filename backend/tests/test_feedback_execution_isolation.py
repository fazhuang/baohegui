"""测试：反馈状态机 + 候选构建 Worker + 策略审批工作流"""

import pytest

from app.engine.feedback_state_machine import (
    FeedbackStateMachine,
    FeedbackStatus,
)
from app.engine.candidate_builder_worker import CandidateBuilderWorker
from app.engine.policy_approval_workflow import (
    PolicyApprovalWorkflow,
    PolicyApprovalStatus,
)


# ═══════════════════════════════════════════════════════
# FeedbackStateMachine
# ═══════════════════════════════════════════════════════

class _FakeFeedbackRecord:
    """模拟 FeedbackRecord — 仅有 status 属性用于状态机"""
    def __init__(self, status=None):
        self.status = status
        self.acknowledged_by = None
        self.acknowledged_at = None
        self.resolved_by = None
        self.resolved_at = None
        self.resolution_note = None
        self.id = 1


class TestFeedbackStateMachine:

    def test_valid_transitions(self):
        sm = FeedbackStateMachine()

        # submitted → acknowledged
        rec = _FakeFeedbackRecord(status=FeedbackStatus.SUBMITTED.value)
        ok, _ = sm.transition(rec, FeedbackStatus.ACKNOWLEDGED.value, admin_id=1)
        assert ok
        assert rec.status == FeedbackStatus.ACKNOWLEDGED.value
        assert rec.acknowledged_by == 1
        assert rec.acknowledged_at is not None

    def test_submitted_to_closed_direct(self):
        """明显误报可直接关闭"""
        rec = _FakeFeedbackRecord(status=FeedbackStatus.SUBMITTED.value)
        ok, _ = FeedbackStateMachine.transition(rec, FeedbackStatus.CLOSED.value)
        assert ok
        assert rec.status == FeedbackStatus.CLOSED.value

    def test_acknowledged_to_resolved(self):
        rec = _FakeFeedbackRecord(status=FeedbackStatus.ACKNOWLEDGED.value)
        ok, _ = FeedbackStateMachine.transition(
            rec, FeedbackStatus.RESOLVED.value, admin_id=2, note="规则已修正"
        )
        assert ok
        assert rec.status == FeedbackStatus.RESOLVED.value
        assert rec.resolved_by == 2
        assert rec.resolution_note == "规则已修正"

    def test_closed_is_terminal(self):
        rec = _FakeFeedbackRecord(status=FeedbackStatus.CLOSED.value)
        ok, msg = FeedbackStateMachine.transition(rec, FeedbackStatus.ACKNOWLEDGED.value)
        assert not ok
        assert "非法" in msg

    def test_resolved_to_closed(self):
        rec = _FakeFeedbackRecord(status=FeedbackStatus.RESOLVED.value)
        ok, _ = FeedbackStateMachine.transition(rec, FeedbackStatus.CLOSED.value)
        assert ok
        assert rec.status == FeedbackStatus.CLOSED.value

    def test_default_status_is_none_is_valid(self):
        """无 status 的记录视为 submitted"""
        rec = _FakeFeedbackRecord(status=None)
        ok, _ = FeedbackStateMachine.transition(rec, FeedbackStatus.ACKNOWLEDGED.value)
        assert ok
        assert rec.status == FeedbackStatus.ACKNOWLEDGED.value

    def test_invalid_transition_rejected(self):
        """回跳不允许：acknowledged → submitted"""
        rec = _FakeFeedbackRecord(status=FeedbackStatus.ACKNOWLEDGED.value)
        ok, msg = FeedbackStateMachine.transition(rec, FeedbackStatus.SUBMITTED.value)
        assert not ok

    def test_can_transition(self):
        assert FeedbackStateMachine.can_transition("submitted", "acknowledged")
        assert FeedbackStateMachine.can_transition("submitted", "closed")
        assert not FeedbackStateMachine.can_transition("closed", "submitted")
        assert not FeedbackStateMachine.can_transition("acknowledged", "submitted")

    def test_get_allowed_transitions(self):
        allowed = FeedbackStateMachine.get_allowed_transitions("submitted")
        assert "acknowledged" in allowed
        assert "closed" in allowed
        assert "resolved" not in allowed

        assert FeedbackStateMachine.get_allowed_transitions("closed") == []


# ═══════════════════════════════════════════════════════
# CandidateBuilderWorker
# ═══════════════════════════════════════════════════════

class TestCandidateBuilderWorker:

    def test_valid_triggers(self):
        w = CandidateBuilderWorker()
        assert "cron" in w.VALID_TRIGGERS
        assert "manual_admin" in w.VALID_TRIGGERS
        assert "scheduler" in w.VALID_TRIGGERS

    def test_invalid_trigger_rejected(self):
        w = CandidateBuilderWorker()
        with pytest.raises(ValueError, match="无效触发来源"):
            # 伪装成 feedback_event 触发 — 必须被拒绝
            w.run(None, trigger="feedback_event")

    def test_initial_state(self):
        w = CandidateBuilderWorker()
        assert w.last_run_at is None
        assert w.last_trigger is None

    def test_worker_does_not_import_feedback(self):
        """候选构建 Worker 不应导入 feedback 模块"""
        import inspect
        src = inspect.getsource(CandidateBuilderWorker)
        # 检查 import 语句，不是 docstring 中的"反馈"字样
        import_lines = [l.strip() for l in src.split("\n") if l.strip().startswith(("from ", "import "))]
        for line in import_lines:
            assert "feedback" not in line, f"Worker 不应导入 feedback 模块: {line}"


# ═══════════════════════════════════════════════════════
# PolicyApprovalWorkflow
# ═══════════════════════════════════════════════════════

class _FakePolicyRecord:
    """模拟策略记录"""
    def __init__(self, status=None):
        self.status = status or PolicyApprovalStatus.DRAFT.value
        self.submitted_at = None
        self.approved_by = None
        self.approved_at = None
        self.approval_note = None
        self.rejected_by = None
        self.rejected_at = None
        self.rejection_reason = None
        self.applied_by = None
        self.applied_at = None
        self.rolled_back_by = None
        self.rolled_back_at = None
        self.rollback_reason = None
        self.id = 1


class TestPolicyApprovalWorkflow:

    # ── 正向流程 ──────────────────────────

    def test_full_happy_path(self):
        """draft → review → approved → applied"""
        wf = PolicyApprovalWorkflow()
        rec = _FakePolicyRecord()

        # draft → review
        ok, _ = wf.submit_for_review(rec)
        assert ok
        assert rec.status == PolicyApprovalStatus.REVIEW.value
        assert rec.submitted_at is not None

        # review → approved
        ok, _ = wf.approve(rec, admin_id=1, note="LGTM")
        assert ok
        assert rec.status == PolicyApprovalStatus.APPROVED.value
        assert rec.approved_by == 1
        assert rec.approval_note == "LGTM"

        # approved → applied
        ok, _ = wf.apply(rec, admin_id=1)
        assert ok
        assert rec.status == PolicyApprovalStatus.APPLIED.value
        assert rec.applied_by == 1

    def test_reject_and_revise_cycle(self):
        """draft → review → rejected → draft → review → approved"""
        wf = PolicyApprovalWorkflow()
        rec = _FakePolicyRecord()

        wf.submit_for_review(rec)
        assert rec.status == PolicyApprovalStatus.REVIEW.value

        wf.reject(rec, admin_id=1, note="法规引用有误")
        assert rec.status == PolicyApprovalStatus.REJECTED.value
        assert rec.rejected_by == 1
        assert rec.rejection_reason == "法规引用有误"

        # 修订后重新提交
        wf.revise(rec)
        assert rec.status == PolicyApprovalStatus.DRAFT.value

        wf.submit_for_review(rec)
        wf.approve(rec, admin_id=1)
        assert rec.status == PolicyApprovalStatus.APPROVED.value

    def test_emergency_rollback(self):
        """applied → rolled_back → draft"""
        wf = PolicyApprovalWorkflow()
        rec = _FakePolicyRecord()

        wf.submit_for_review(rec)
        wf.approve(rec, admin_id=1)
        wf.apply(rec, admin_id=1)
        assert rec.status == PolicyApprovalStatus.APPLIED.value

        # 紧急回滚
        ok, _ = wf.rollback(rec, admin_id=2, reason="生产故障，立即回滚")
        assert ok
        assert rec.status == PolicyApprovalStatus.ROLLED_BACK.value
        assert rec.rolled_back_by == 2
        assert "ROLLBACK" in rec.rollback_reason

        # 修复后回到草稿
        ok, _ = wf.revise(rec)
        assert ok
        assert rec.status == PolicyApprovalStatus.DRAFT.value

    # ── 非法转换 ──────────────────────────

    def test_cannot_skip_review(self):
        """draft → approved 不允许（必须经过 review）"""
        rec = _FakePolicyRecord()
        ok, msg = PolicyApprovalWorkflow.approve(rec, admin_id=1)
        assert not ok
        assert "非法" in msg

    def test_cannot_apply_without_approval(self):
        """review → applied 不允许（必须先 approved）"""
        rec = _FakePolicyRecord()
        PolicyApprovalWorkflow.submit_for_review(rec)
        ok, msg = PolicyApprovalWorkflow.apply(rec, admin_id=1)
        assert not ok

    def test_cannot_reopen_applied(self):
        """applied → draft 不允许（必须通过 rolled_back）"""
        rec = _FakePolicyRecord()
        wf = PolicyApprovalWorkflow()
        wf.submit_for_review(rec)
        wf.approve(rec, admin_id=1)
        wf.apply(rec, admin_id=1)
        ok, msg = wf.revise(rec)
        assert not ok

    def test_cannot_double_apply(self):
        """applied → applied 不允许"""
        rec = _FakePolicyRecord()
        wf = PolicyApprovalWorkflow()
        wf.submit_for_review(rec)
        wf.approve(rec, admin_id=1)
        wf.apply(rec, admin_id=1)
        ok, msg = wf.apply(rec, admin_id=1)
        assert not ok

    def test_reject_from_draft_invalid(self):
        """draft → rejected 不允许（必须先 review）"""
        rec = _FakePolicyRecord()
        ok, msg = PolicyApprovalWorkflow.reject(rec, admin_id=1)
        assert not ok

    # ── 执行链影响 ──────────────────────────

    def test_only_applied_affects_execution(self):
        wf = PolicyApprovalWorkflow()
        assert not wf.affects_execution(PolicyApprovalStatus.DRAFT.value)
        assert not wf.affects_execution(PolicyApprovalStatus.REVIEW.value)
        assert not wf.affects_execution(PolicyApprovalStatus.APPROVED.value)
        assert not wf.affects_execution(PolicyApprovalStatus.REJECTED.value)
        assert wf.affects_execution(PolicyApprovalStatus.APPLIED.value)
        assert not wf.affects_execution(PolicyApprovalStatus.ROLLED_BACK.value)

    def test_rolled_back_no_longer_affects_execution(self):
        """回滚后不再影响执行链"""
        wf = PolicyApprovalWorkflow()
        assert not wf.affects_execution(PolicyApprovalStatus.ROLLED_BACK.value)

    # ── 辅助方法 ──────────────────────────

    def test_can_transition(self):
        assert PolicyApprovalWorkflow.can_transition("draft", "review")
        assert PolicyApprovalWorkflow.can_transition("review", "approved")
        assert PolicyApprovalWorkflow.can_transition("review", "rejected")
        assert PolicyApprovalWorkflow.can_transition("rejected", "draft")
        assert PolicyApprovalWorkflow.can_transition("approved", "applied")
        assert PolicyApprovalWorkflow.can_transition("applied", "rolled_back")

        assert not PolicyApprovalWorkflow.can_transition("draft", "applied")
        assert not PolicyApprovalWorkflow.can_transition("applied", "draft")

    def test_get_allowed_transitions(self):
        allowed = PolicyApprovalWorkflow.get_allowed_transitions("review")
        assert "approved" in allowed
        assert "rejected" in allowed
        assert "draft" not in allowed

        allowed = PolicyApprovalWorkflow.get_allowed_transitions("applied")
        assert "rolled_back" in allowed
        assert len(allowed) == 1
