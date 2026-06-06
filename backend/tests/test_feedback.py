"""审查反馈回路测试"""
import pytest


class TestFeedbackService:
    """反馈服务单元测试"""

    def test_feedback_service_import(self):
        from app.services.feedback_service import (
            FeedbackRecord,
            FeedbackService,
            RuleConfidence,
            feedback_service,
        )

        assert feedback_service is not None
        assert isinstance(feedback_service, FeedbackService)

    def test_submit_feedback_confirm(self, db_session):
        """确认反馈应提升置信度"""
        from app.services.feedback_service import (
            FeedbackRecord,
            RuleConfidence,
            feedback_service,
        )

        result = feedback_service.submit_feedback(
            db=db_session,
            report_id=1,
            rule_id="R001",
            user_id=1,
            feedback_type="confirm",
            comment="此规则判断正确",
        )

        assert result["rule_id"] == "R001"
        # 基准 1.0 + 0.02 boost，但 capped at MAX_CONFIDENCE=1.0
        assert result["current_confidence"] == 1.0
        assert result["total_feedbacks"] == 1
        assert result["needs_review"] is False
        assert "message" in result

        # 验证记录已持久化
        record = db_session.query(FeedbackRecord).first()
        assert record is not None
        assert record.feedback_type == "confirm"
        assert record.comment == "此规则判断正确"

    def test_submit_feedback_false_positive(self, db_session):
        """误报反馈应降低置信度"""
        from app.services.feedback_service import (
            FeedbackRecord,
            RuleConfidence,
            feedback_service,
        )

        result = feedback_service.submit_feedback(
            db=db_session,
            report_id=1,
            rule_id="R002",
            user_id=1,
            feedback_type="false_positive",
        )

        assert result["rule_id"] == "R002"
        assert result["current_confidence"] < 1.0  # 基准 1.0 - 0.05 penalty
        assert result["total_feedbacks"] == 1

        # 验证记录已持久化
        record = db_session.query(FeedbackRecord).first()
        assert record is not None
        assert record.feedback_type == "false_positive"

    def test_submit_feedback_missed(self, db_session):
        """遗漏反馈不应改变置信度，但计入反馈总数"""
        from app.services.feedback_service import feedback_service

        result = feedback_service.submit_feedback(
            db=db_session,
            report_id=1,
            rule_id="R003",
            user_id=1,
            feedback_type="missed",
            comment="漏检了这条",
        )

        assert result["rule_id"] == "R003"
        assert result["current_confidence"] == 1.0  # missed 不调整置信度
        assert result["total_feedbacks"] == 1
        assert result["needs_review"] is False

    def test_false_positive_threshold_triggers_review(self, db_session):
        """累积3次误报应自动标记为待审核"""
        from app.services.feedback_service import (
            RuleConfidence,
            feedback_service,
        )

        for i in range(3):
            result = feedback_service.submit_feedback(
                db=db_session,
                report_id=i + 1,
                rule_id="R004",
                user_id=1,
                feedback_type="false_positive",
            )

        # 第3次应触发审核标记
        assert result["needs_review"] is True
        # 1.0 - 0.15 = 0.85 (floating point approximate)
        assert result["current_confidence"] == pytest.approx(1.0 - 3 * 0.05)

        # 验证数据库中的标记
        conf = (
            db_session.query(RuleConfidence)
            .filter(RuleConfidence.rule_id == "R004")
            .first()
        )
        assert conf is not None
        assert conf.needs_review == 1
        assert conf.false_positive_count == 3

    def test_confidence_floor(self, db_session):
        """置信度不应低于下限 0.5"""
        from app.services.feedback_service import feedback_service

        for i in range(20):  # 远超下限所需的次数
            feedback_service.submit_feedback(
                db=db_session,
                report_id=i + 1,
                rule_id="R005",
                user_id=1,
                feedback_type="false_positive",
            )

        last = feedback_service.submit_feedback(
            db=db_session,
            report_id=999,
            rule_id="R005",
            user_id=1,
            feedback_type="false_positive",
        )

        assert last["current_confidence"] == 0.5  # 不应低于下限

    def test_confidence_ceiling(self, db_session):
        """置信度不应超过上限 1.0"""
        from app.services.feedback_service import feedback_service

        for i in range(10):
            feedback_service.submit_feedback(
                db=db_session,
                report_id=i + 1,
                rule_id="R006",
                user_id=1,
                feedback_type="confirm",
            )

        last = feedback_service.submit_feedback(
            db=db_session,
            report_id=999,
            rule_id="R006",
            user_id=1,
            feedback_type="confirm",
        )

        assert last["current_confidence"] == 1.0

    def test_get_rule_confidence(self, db_session):
        """获取规则置信度信息"""
        from app.services.feedback_service import feedback_service

        # 先提交一些反馈
        feedback_service.submit_feedback(
            db=db_session,
            report_id=1,
            rule_id="R007",
            user_id=1,
            feedback_type="confirm",
        )

        info = feedback_service.get_rule_confidence(db_session, "R007")
        assert info is not None
        assert info["rule_id"] == "R007"
        assert info["total_feedbacks"] == 1
        assert info["confirm_count"] == 1
        assert info["false_positive_count"] == 0

    def test_get_rule_confidence_nonexistent(self, db_session):
        """查询不存在的规则应返回 None"""
        from app.services.feedback_service import feedback_service

        info = feedback_service.get_rule_confidence(db_session, "NOEXIST")
        assert info is None

    def test_get_rules_needing_review(self, db_session):
        """获取待审核规则列表"""
        from app.services.feedback_service import feedback_service

        # 使 R008 触发审核
        for i in range(3):
            feedback_service.submit_feedback(
                db=db_session,
                report_id=i + 1,
                rule_id="R008",
                user_id=1,
                feedback_type="false_positive",
            )

        rules = feedback_service.get_rules_needing_review(db_session)
        assert len(rules) >= 1
        assert any(r["rule_id"] == "R008" for r in rules)

    def test_invalid_feedback_type(self, db_session):
        """无效的反馈类型应抛出异常"""
        from app.services.feedback_service import feedback_service

        with pytest.raises(ValueError, match="无效的反馈类型"):
            feedback_service.submit_feedback(
                db=db_session,
                report_id=1,
                rule_id="R009",
                user_id=1,
                feedback_type="invalid_type",
            )


class TestFeedbackAPI:
    """反馈 API 端点测试"""

    def test_submit_feedback_endpoint(self, client, auth_headers):
        """反馈提交API测试 — 报告不存在时返回 404"""
        resp = client.post(
            "/api/report/feedback",
            json={
                "report_id": 1,
                "rule_id": "R001",
                "feedback_type": "false_positive",
                "comment": "此规则不适用于该项目",
            },
            headers=auth_headers,
        )
        # 报告不存在返回 404
        assert resp.status_code == 404

    def test_feedback_endpoint_with_report(self, client, auth_headers, db_session):
        """当报告存在时应正常处理反馈"""
        from app.models.document import ComplianceReport

        # 创建测试报告
        report = ComplianceReport(
            file_id=1,
            total_score=90.0,
            violation_count=2,
            report_data='{"result": "passed"}',
        )
        db_session.add(report)
        db_session.commit()
        db_session.refresh(report)

        resp = client.post(
            "/api/report/feedback",
            json={
                "report_id": report.id,
                "rule_id": "R010",
                "feedback_type": "confirm",
            },
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["rule_id"] == "R010"
        # 基准 1.0 + 0.02 = 1.02，capped at MAX_CONFIDENCE=1.0
        assert data["current_confidence"] == 1.0

    def test_feedback_requires_auth(self, client):
        """反馈API需要认证"""
        resp = client.post(
            "/api/report/feedback",
            json={"report_id": 1, "rule_id": "R001", "feedback_type": "confirm"},
        )
        assert resp.status_code in (401, 403)

    def test_feedback_invalid_type(self, client, auth_headers, db_session):
        """无效反馈类型返回 400"""
        from app.models.document import ComplianceReport

        report = ComplianceReport(
            file_id=1,
            total_score=90.0,
            violation_count=2,
            report_data='{"result": "passed"}',
        )
        db_session.add(report)
        db_session.commit()
        db_session.refresh(report)

        resp = client.post(
            "/api/report/feedback",
            json={
                "report_id": report.id,
                "rule_id": "R011",
                "feedback_type": "bad_type",
            },
            headers=auth_headers,
        )

        assert resp.status_code == 400

    def test_rules_needing_review_endpoint(self, client, auth_headers):
        """待审核规则列表 API"""
        resp = client.get(
            "/api/report/feedback/rules-needing-review",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "rules" in data
        assert isinstance(data["rules"], list)

    def test_rules_needing_review_requires_auth(self, client):
        """待审核规则 API 需要认证"""
        resp = client.get("/api/report/feedback/rules-needing-review")
        assert resp.status_code in (401, 403)
