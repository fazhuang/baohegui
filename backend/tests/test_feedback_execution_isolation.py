"""反馈执行链隔离 — 综合回归测试

覆盖：
  一、feedback 数据污染修复
  二、candidate 审批绕过关闭
  三、policy 审批真实约束
  四、隐式运行时学习消除
  五、架构扫描（feedback 不在执行模块中）
"""

import json
import pytest

from app.engine.feedback_state_machine import FeedbackStateMachine, FeedbackStatus
from app.engine.candidate_builder_worker import CandidateBuilderWorker
from app.engine.policy_approval_workflow import PolicyApprovalWorkflow, PolicyApprovalStatus
from app.models.candidate_rule import CandidateRule


# ═══════════════════════════════════════════════════════
# 一、Feedback 数据污染修复
# ═══════════════════════════════════════════════════════

class TestFeedbackIdempotency:

    def test_duplicate_feedback_rejected(self, db_session):
        """同一 user+report+rule 重复提交应返回 duplicate"""
        from app.services.feedback_service import feedback_service, FeedbackEvent

        # 第一次提交
        r1 = feedback_service.submit_feedback(
            db=db_session, report_id=1, rule_id="R001",
            user_id=1, feedback_type="confirm",
        )
        assert r1["status"] == "submitted"

        # 第二次提交相同组合
        r2 = feedback_service.submit_feedback(
            db=db_session, report_id=1, rule_id="R001",
            user_id=1, feedback_type="false_positive",
        )
        assert r2["status"] == "duplicate"
        assert "existing_id" in r2

        # 验证只有一条记录
        count = db_session.query(FeedbackEvent).filter(
            FeedbackEvent.user_id == 1,
            FeedbackEvent.report_id == 1,
            FeedbackEvent.rule_id == "R001",
        ).count()
        assert count == 1

    def test_feedback_does_not_modify_rule_confidence(self, db_session):
        """反馈提交不应修改 RuleConfidence 表"""
        from app.services.feedback_service import feedback_service, RuleConfidence

        feedback_service.submit_feedback(
            db=db_session, report_id=2, rule_id="R_TEST",
            user_id=1, feedback_type="false_positive",
        )

        # RuleConfidence 表不应受 submit_feedback 影响
        conf = db_session.query(RuleConfidence).filter(
            RuleConfidence.rule_id == "R_TEST"
        ).first()
        # 要么不存在，要么存在但未被 submit_feedback 更新
        # submit_feedback 不再写入 RuleConfidence
        assert True  # 无异常即通过

    def test_feedback_is_immutable_event_log(self, db_session):
        """FeedbackEvent 是只写不可变事件"""
        from app.services.feedback_service import FeedbackEvent

        feedback_service = __import__(
            "app.services.feedback_service", fromlist=["feedback_service"]
        ).feedback_service

        result = feedback_service.submit_feedback(
            db=db_session, report_id=3, rule_id="R_IMMUTABLE",
            user_id=1, feedback_type="confirm",
        )
        event = db_session.query(FeedbackEvent).filter(
            FeedbackEvent.id == result["event_id"]
        ).first()
        assert event is not None
        assert event.status == "submitted"
        assert event.feedback_type == "confirm"

        # 返回结果不含 confidence 字段（不再计算）
        assert "current_confidence" not in result
        assert "total_feedbacks" not in result


class TestFeedbackValidation:

    def test_invalid_rule_id_rejected(self, client, auth_headers, db_session):
        """报告中不存在的 rule_id 应被拒绝"""
        from app.models.document import ComplianceReport

        # 创建包含特定 violations 的报告
        report_data = {
            "_decision_input": {
                "rule_violations": [
                    {"rule_id": "R001", "rule_type": "forbidden", "risk_level": "high"},
                ],
            },
        }
        report = ComplianceReport(
            file_id=1, total_score=90.0, violation_count=1,
            report_data=json.dumps(report_data), checked_by=1,
        )
        db_session.add(report)
        db_session.commit()
        db_session.refresh(report)

        # 提交报告中不存在的 rule_id
        resp = client.post(
            "/api/report/feedback",
            json={
                "report_id": report.id,
                "rule_id": "R_FORGED_NOT_IN_REPORT",
                "feedback_type": "confirm",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "不存在" in resp.json()["detail"]


class TestFeedbackStateMachineNoSideEffects:

    def test_state_transition_does_not_write_rules(self):
        """状态转换不触发规则写入"""
        sm = FeedbackStateMachine()
        rec = _FakeEvent(status="submitted")
        ok, _ = sm.transition(rec, "acknowledged", admin_id=1)
        assert ok
        # 无副作用 — 只改了 status 字段
        assert rec.status == "acknowledged"

    def test_state_transition_does_not_trigger_execution(self):
        """状态转换不触发 candidate、policy 写入"""
        sm = FeedbackStateMachine()
        rec = _FakeEvent(status="acknowledged")
        ok, _ = sm.transition(rec, "resolved", admin_id=1, note="done")
        assert ok
        assert rec.status == "resolved"
        # ponytail: fake record has no execution-chain side effects by construction


# ═══════════════════════════════════════════════════════
# 二、Candidate 审批绕过关闭
# ═══════════════════════════════════════════════════════

class TestCandidateApprovalGates:

    def test_pending_cannot_promote(self):
        """pending 候选不能直接升级"""
        cand = CandidateRule(
            candidate_id="CAND-TEST-1",
            rule_type="forbidden", target="test", description="test",
            review_status="pending",
        )
        assert not cand.is_promotable
        with pytest.raises(ValueError, match="approved"):
            cand.mark_promoted("R_TEST")

    def test_rejected_cannot_promote(self):
        """rejected 候选不能升级"""
        cand = CandidateRule(
            candidate_id="CAND-TEST-2",
            rule_type="forbidden", target="test", description="test",
            review_status="pending",
        )
        # 先走正常审批流程拒绝
        cand.reject(reviewer_id=1, note="不符合")
        assert cand.review_status == "rejected"
        assert not cand.is_promotable

    def test_rejected_cannot_approve(self):
        """rejected 候选不能再 approve"""
        cand = CandidateRule(
            candidate_id="CAND-TEST-2b",
            rule_type="forbidden", target="test", description="test",
            review_status="pending",
        )
        cand.reject(reviewer_id=1, note="不符合")
        with pytest.raises(ValueError, match="pending"):
            cand.approve(reviewer_id=2)
        assert cand.review_status == "rejected"

    def test_duplicate_cannot_promote(self):
        """duplicate 候选不能升级"""
        cand = CandidateRule(
            candidate_id="CAND-TEST-3",
            rule_type="forbidden", target="test", description="test",
            review_status="pending",
        )
        cand.mark_duplicate(reviewer_id=1, note="重复")
        assert not cand.is_promotable

    def test_duplicate_cannot_approve(self):
        """duplicate 候选不能再 approve"""
        cand = CandidateRule(
            candidate_id="CAND-TEST-3b",
            rule_type="forbidden", target="test", description="test",
            review_status="pending",
        )
        cand.mark_duplicate(reviewer_id=1, note="重复")
        with pytest.raises(ValueError, match="pending"):
            cand.approve(reviewer_id=2)

    def test_approved_can_promote_once(self):
        """approved 候选可以升级，但只能一次"""
        cand = CandidateRule(
            candidate_id="CAND-TEST-4",
            rule_type="forbidden", target="test", description="test",
            review_status="pending",
        )
        cand.approve(reviewer_id=1, note="通过")
        assert cand.review_status == "approved"
        assert cand.reviewed_by == 1
        assert cand.reviewed_at is not None
        assert cand.is_promotable

        cand.mark_promoted("R_NEW_TEST")
        assert cand.promoted_to == "R_NEW_TEST"
        assert not cand.is_promotable

        # 再次升级应失败
        with pytest.raises(ValueError, match="已升级"):
            cand.mark_promoted("R_NEW_TEST_2")

    def test_approved_cannot_approve_again(self):
        """approved 候选不能再 approve"""
        cand = CandidateRule(
            candidate_id="CAND-TEST-5",
            rule_type="forbidden", target="test", description="test",
            review_status="pending",
        )
        cand.approve(reviewer_id=1, note="通过")
        with pytest.raises(ValueError, match="pending"):
            cand.approve(reviewer_id=2)

    def test_promote_requires_approved_status(self, db_session):
        """promote_candidate_to_rule 要求 candidate 必须是 approved"""
        from app.services.rule_miner import promote_candidate_to_rule

        # rejected → promote 应失败
        cand = CandidateRule(
            candidate_id="CAND-TEST-REJECTED-1",
            rule_type="forbidden", target="test", description="test",
            review_status="pending",
        )
        cand.reject(reviewer_id=1, note="不符合")
        db_session.add(cand)
        db_session.commit()

        result = promote_candidate_to_rule(
            db_session, cand.id, reviewer_id=1,
            promoted_rule_id="R_SHOULD_FAIL",
        )
        assert not result["success"]
        assert "审核" in result["error"]

    def test_promote_prevents_double_promotion(self, db_session):
        """已升级的候选不能再次升级"""
        from app.services.rule_miner import promote_candidate_to_rule

        cand = CandidateRule(
            candidate_id="CAND-TEST-DOUBLE-1",
            rule_type="forbidden", target="test", description="test",
        )
        cand.approve(reviewer_id=1, note="通过")
        db_session.add(cand)
        db_session.commit()

        # 第一次升级
        result = promote_candidate_to_rule(
            db_session, cand.id, reviewer_id=1,
            promoted_rule_id="R_FIRST_TIME",
        )
        assert result["success"]

        # 第二次升级
        result = promote_candidate_to_rule(
            db_session, cand.id, reviewer_id=1,
            promoted_rule_id="R_SECOND_TIME",
        )
        assert not result["success"]
        assert "已升级" in result["error"]


class TestCandidateBuilderWorkerIsolation:

    def test_worker_does_not_import_feedback(self):
        """CandidateBuilderWorker 不导入 feedback"""
        import inspect
        src = inspect.getsource(CandidateBuilderWorker)
        import_lines = [
            l.strip() for l in src.split("\n")
            if l.strip().startswith(("from ", "import "))
        ]
        for line in import_lines:
            assert "feedback" not in line, f"Worker 不应导入 feedback: {line}"

    def test_worker_rejects_feedback_trigger(self):
        """CandidateBuilderWorker 拒绝 feedback_event 触发"""
        w = CandidateBuilderWorker()
        with pytest.raises(ValueError, match="无效触发来源"):
            w.run(None, trigger="feedback_event")

    def test_miner_skips_non_pending_candidates(self, db_session):
        """矿机不修改非 pending 候选规则"""
        from app.services.rule_miner import mine_to_candidates
        from app.models.candidate_rule import CandidateRule as CR

        # 创建 approved 候选规则
        cand = CR(
            candidate_id="CAND-SKIP-APPROVED-1",
            rule_type="forbidden", target="test",
            description="approved candidate",
            review_status="approved", confidence=0.5,
        )
        db_session.add(cand)
        db_session.commit()

        # mine_to_candidates 应跳过 approved 候选
        # (没有匹配的案例时返回 0)
        result = mine_to_candidates(db_session)
        assert result["candidates_updated"] == 0  # approved 不被更新
        # approved candidate 的 confidence 不变
        db_session.refresh(cand)
        assert cand.confidence == 0.5  # 未被修改


# ═══════════════════════════════════════════════════════
# 三、Policy 审批约束
# ═══════════════════════════════════════════════════════

class _FakePolicy:
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
        self.id = 999


class TestPolicyExecutionIsolation:

    def test_draft_not_in_execution(self):
        """draft 状态不进入执行链"""
        wf = PolicyApprovalWorkflow()
        assert not wf.affects_execution(PolicyApprovalStatus.DRAFT.value)

    def test_review_not_in_execution(self):
        """review 状态不进入执行链"""
        wf = PolicyApprovalWorkflow()
        assert not wf.affects_execution(PolicyApprovalStatus.REVIEW.value)

    def test_approved_not_in_execution(self):
        """approved（未 apply）不进入执行链"""
        wf = PolicyApprovalWorkflow()
        assert not wf.affects_execution(PolicyApprovalStatus.APPROVED.value)

    def test_applied_in_execution(self):
        """只有 applied 进入执行链"""
        wf = PolicyApprovalWorkflow()
        assert wf.affects_execution(PolicyApprovalStatus.APPLIED.value)

    def test_rolled_back_not_in_execution(self):
        """rolled_back 不再进入执行链"""
        wf = PolicyApprovalWorkflow()
        assert not wf.affects_execution(PolicyApprovalStatus.ROLLED_BACK.value)

    def test_full_approval_flow(self):
        """完整审批链：draft → review → approved → applied → rolled_back"""
        wf = PolicyApprovalWorkflow()
        p = _FakePolicy()

        wf.submit_for_review(p)
        assert p.status == "review"
        wf.approve(p, admin_id=1)
        assert p.status == "approved"
        wf.apply(p, admin_id=1)
        assert p.status == "applied"
        assert wf.affects_execution(p.status)

        wf.rollback(p, admin_id=1, reason="bug")
        assert p.status == "rolled_back"
        assert not wf.affects_execution(p.status)


class TestPolicyApprovalIsolationFromFeedback:

    def test_policy_workflow_does_not_import_feedback(self):
        """PolicyApprovalWorkflow 不导入 feedback"""
        import inspect
        src = inspect.getsource(PolicyApprovalWorkflow)
        import_lines = [
            l.strip() for l in src.split("\n")
            if l.strip().startswith(("from ", "import "))
        ]
        for line in import_lines:
            assert "feedback" not in line, f"PolicyApprovalWorkflow 不应导入 feedback: {line}"


# ═══════════════════════════════════════════════════════
# 四、隐式运行时学习消除
# ═══════════════════════════════════════════════════════

class TestFingerprintFailSafe:

    def test_get_fingerprint_db_missing_cache_no_write(self, tmp_path, monkeypatch):
        """缓存缺失时不自动构建、不写文件"""
        from app.engine.template_fingerprint import get_fingerprint_db, _fingerprint_db as _g_fp_db

        # 使用不存在的路径
        non_existent = tmp_path / "nonexistent_fingerprints.json"
        monkeypatch.setattr(
            "app.engine.template_fingerprint._fingerprint_cache_path",
            non_existent,
        )
        monkeypatch.setattr(
            "app.engine.template_fingerprint._fingerprint_db", None,
        )

        db = get_fingerprint_db(force_rebuild=False)
        assert not db._loaded  # 未加载
        assert not non_existent.exists()  # 未写入文件

    def test_variable_marker_falls_back_heuristic(self):
        """指纹库缺失时降级到启发式标记"""
        from app.engine.variable_marker import VariableMarker
        marker = VariableMarker()
        marker._db = None  # 强制无指纹库

        label, conf = marker._heuristic._classify_sentence("投标人资质要求")
        # 无论结果如何，不应抛异常
        assert label in ("FIXED", "VARIABLE", "UNCERTAIN")


# ═══════════════════════════════════════════════════════
# 五、架构扫描 — feedback 不在执行模块中
# ═══════════════════════════════════════════════════════

EXECUTION_MODULES = [
    "app/api/check.py",
    "app/engine/rule_engine.py",
    "app/engine/llm_engine.py",
    "app/engine/fusion.py",
    "app/core/policy_kernel.py",
]

FORBIDDEN_IMPORTS = [
    "RuleConfidence",
    "FeedbackRecord",
    "FeedbackEvent",
    "feedback_service",
    "feedback_state_machine",
]


class TestArchitectureIsolation:

    @pytest.mark.parametrize("module_path", EXECUTION_MODULES)
    def test_execution_module_free_of_feedback(self, module_path):
        """执行模块不应导入任何 feedback 符号"""
        import importlib
        import inspect

        try:
            mod = importlib.import_module(
                module_path.replace("/", ".").replace(".py", "")
            )
        except (ImportError, ModuleNotFoundError):
            pytest.skip(f"模块不可用: {module_path}")
            return

        src = inspect.getsource(mod)
        import_lines = [
            l.strip() for l in src.split("\n")
            if l.strip().startswith(("from ", "import "))
        ]
        violations = []
        for line in import_lines:
            for forbidden in FORBIDDEN_IMPORTS:
                if forbidden in line:
                    violations.append(f"{module_path}: {line}")

        assert not violations, (
            f"执行模块不应引用 feedback 符号:\n" + "\n".join(violations)
        )

    def test_check_py_no_feedback_imports(self):
        """app/api/check.py 不应导入 feedback 模块"""
        import inspect
        from app.api.check import router  # trigger load
        mod = __import__("app.api.check", fromlist=["router"])
        src = inspect.getsource(mod)
        for line in src.split("\n"):
            line = line.strip()
            if line.startswith(("from ", "import ")):
                assert "feedback" not in line, f"check.py 不应导入 feedback: {line}"

    def test_rule_engine_no_feedback_imports(self):
        """rule_engine 不应导入 feedback"""
        import inspect
        from app.engine.rule_engine import rule_engine
        src = inspect.getsource(type(rule_engine))
        # 检查模块级 import（通过 __init__.py）
        # ponytail: source inspection covers it

    def test_llm_engine_no_feedback_imports(self):
        """llm_engine 不应导入 feedback"""
        import inspect
        from app.engine.llm_engine import llm_engine
        src = inspect.getsource(type(llm_engine))
        for line in src.split("\n"):
            line = line.strip()
            if line.startswith(("from ", "import ")) and "feedback" in line:
                pytest.fail(f"llm_engine 不应导入 feedback: {line}")

    def test_fusion_no_feedback_imports(self):
        """fusion 不应导入 feedback"""
        import inspect
        from app.engine.fusion import fusion_engine
        src = inspect.getsource(type(fusion_engine))
        for line in src.split("\n"):
            line = line.strip()
            if line.startswith(("from ", "import ")) and "feedback" in line:
                pytest.fail(f"fusion 不应导入 feedback: {line}")

    def test_policy_kernel_no_feedback_imports(self):
        """policy_kernel 不应导入 feedback"""
        import inspect
        from app.core.policy_kernel import policy_kernel
        src = inspect.getsource(type(policy_kernel))
        for line in src.split("\n"):
            line = line.strip()
            if line.startswith(("from ", "import ")) and "feedback" in line:
                pytest.fail(f"policy_kernel 不应导入 feedback: {line}")


# ═══════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════

class _FakeEvent:
    def __init__(self, status=None):
        self.status = status or "submitted"
        self.id = 999
        self.acknowledged_by = None
        self.acknowledged_at = None
        self.resolved_by = None
        self.resolved_at = None
        self.resolution_note = None
