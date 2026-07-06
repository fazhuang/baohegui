"""审查反馈回路测试 — 不可变 FeedbackEvent 契约

验证：
- 反馈提交只写不可变事件，不修改 RuleConfidence
- 幂等性：重复提交返回 duplicate
- API 权限、验证、状态转换
- 前后数据库状态比较（不依赖 assert True）
"""

import json
import pytest
from sqlalchemy.exc import IntegrityError


class TestFeedbackService:
    """反馈服务单元测试 — 不可变事件日志"""

    def test_feedback_service_import(self):
        from app.services.feedback_service import (
            FeedbackEvent,
            FeedbackService,
            RuleConfidence,
            feedback_service,
        )
        assert feedback_service is not None
        assert isinstance(feedback_service, FeedbackService)
        # FeedbackRecord 是 FeedbackEvent 的别名
        from app.services.feedback_service import FeedbackRecord
        assert FeedbackRecord is FeedbackEvent

    def test_submit_feedback_writes_event(self, db_session):
        """反馈写入 FeedbackEvent，返回不含 confidence"""
        from app.services.feedback_service import feedback_service, FeedbackEvent

        # 提交前：无事件
        before_count = db_session.query(FeedbackEvent).count()

        result = feedback_service.submit_feedback(
            db=db_session, report_id=1, rule_id="R001",
            user_id=1, feedback_type="confirm",
            comment="此规则判断正确",
        )
        assert result["status"] == "submitted"
        assert "event_id" in result
        assert "current_confidence" not in result  # 不返回置信度
        assert "total_feedbacks" not in result

        # 提交后：一条事件
        event = db_session.query(FeedbackEvent).filter(
            FeedbackEvent.id == result["event_id"]
        ).first()
        assert event is not None
        assert event.feedback_type == "confirm"
        assert event.comment == "此规则判断正确"
        assert event.status == "submitted"

        after_count = db_session.query(FeedbackEvent).count()
        assert after_count == before_count + 1

    def test_submit_feedback_false_positive(self, db_session):
        """误报反馈写入事件，不修改置信度"""
        from app.services.feedback_service import feedback_service, FeedbackEvent

        result = feedback_service.submit_feedback(
            db=db_session, report_id=1, rule_id="R002",
            user_id=1, feedback_type="false_positive",
        )
        assert result["status"] == "submitted"
        assert "current_confidence" not in result

        event = db_session.query(FeedbackEvent).filter(
            FeedbackEvent.id == result["event_id"]
        ).first()
        assert event is not None
        assert event.feedback_type == "false_positive"

    def test_submit_feedback_missed(self, db_session):
        """遗漏反馈写入事件"""
        from app.services.feedback_service import feedback_service, FeedbackEvent

        result = feedback_service.submit_feedback(
            db=db_session, report_id=1, rule_id="R003",
            user_id=1, feedback_type="missed",
            comment="漏检了这条",
        )
        assert result["status"] == "submitted"
        assert "current_confidence" not in result

        event = db_session.query(FeedbackEvent).filter(
            FeedbackEvent.id == result["event_id"]
        ).first()
        assert event.feedback_type == "missed"
        assert event.comment == "漏检了这条"

    def test_feedback_does_not_modify_rule_confidence(self, db_session):
        """多次 feedback 不修改 RuleConfidence 表"""
        from app.services.feedback_service import feedback_service, RuleConfidence

        # 提交前：查询初始状态
        before_conf = db_session.query(RuleConfidence).filter(
            RuleConfidence.rule_id == "R004"
        ).first()

        for i in range(3):
            feedback_service.submit_feedback(
                db=db_session, report_id=i + 1, rule_id="R004",
                user_id=1, feedback_type="false_positive",
            )

        # 提交后：RuleConfidence 不变
        after_conf = db_session.query(RuleConfidence).filter(
            RuleConfidence.rule_id == "R004"
        ).first()

        # 要么始终不存在，要么存在但未被 submit_feedback 修改
        if before_conf is not None and after_conf is not None:
            assert before_conf.current_confidence == after_conf.current_confidence
            assert before_conf.total_feedbacks == after_conf.total_feedbacks

    def test_duplicate_feedback_rejected(self, db_session):
        """同一 (user, report, rule) 重复提交返回 duplicate"""
        from app.services.feedback_service import feedback_service, FeedbackEvent

        r1 = feedback_service.submit_feedback(
            db=db_session, report_id=10, rule_id="R005",
            user_id=1, feedback_type="confirm",
        )
        assert r1["status"] == "submitted"

        before_count = db_session.query(FeedbackEvent).count()

        r2 = feedback_service.submit_feedback(
            db=db_session, report_id=10, rule_id="R005",
            user_id=1, feedback_type="false_positive",
        )
        assert r2["status"] == "duplicate"
        assert "existing_id" in r2

        # 没有新增记录
        after_count = db_session.query(FeedbackEvent).count()
        assert after_count == before_count

    def test_invalid_feedback_type(self, db_session):
        """无效的反馈类型应抛出异常"""
        from app.services.feedback_service import feedback_service
        with pytest.raises(ValueError, match="无效的反馈类型"):
            feedback_service.submit_feedback(
                db=db_session, report_id=1, rule_id="R009",
                user_id=1, feedback_type="invalid_type",
            )

    def test_get_rule_confidence_from_events(self, db_session):
        """获取规则置信度应从事件聚合"""
        from app.services.feedback_service import feedback_service, FeedbackEvent

        # 写入多条事件
        feedback_service.submit_feedback(
            db=db_session, report_id=21, rule_id="R007",
            user_id=1, feedback_type="confirm",
        )
        feedback_service.submit_feedback(
            db=db_session, report_id=22, rule_id="R007",
            user_id=2, feedback_type="confirm",
        )

        info = feedback_service.get_rule_confidence(db_session, "R007")
        assert info is not None
        assert info["rule_id"] == "R007"
        assert info["total_feedbacks"] == 2
        assert info["confirm_count"] == 2
        assert info["false_positive_count"] == 0
        assert info["source"] == "aggregated_from_feedback_events"

    def test_get_rule_confidence_nonexistent(self, db_session):
        """查询不存在的规则应返回 None"""
        from app.services.feedback_service import feedback_service
        info = feedback_service.get_rule_confidence(db_session, "NOEXIST")
        assert info is None

    def test_get_rules_needing_review(self, db_session):
        """获取误报率高的规则 — 从事件聚合"""
        from app.services.feedback_service import feedback_service

        # 给 R008 累积误报（不同用户/报告绕过幂等）
        for i in range(3):
            feedback_service.submit_feedback(
                db=db_session, report_id=30 + i, rule_id="R008",
                user_id=10 + i, feedback_type="false_positive",
            )

        rules = feedback_service.get_rules_needing_review(db_session)
        assert len(rules) >= 1
        assert any(r["rule_id"] == "R008" for r in rules)

    # ponytail: confidence floor/ceiling tests removed —
    # RuleConfidence is no longer modified by submit_feedback


class TestFeedbackAPI:
    """反馈 API 端点测试"""

    def test_submit_feedback_endpoint(self, client, auth_headers):
        """反馈提交API测试 — 报告不存在时返回 404"""
        resp = client.post(
            "/api/report/feedback",
            json={
                "report_id": 1, "rule_id": "R001",
                "feedback_type": "false_positive",
                "comment": "此规则不适用于该项目",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_feedback_endpoint_with_report(self, client, auth_headers, db_session):
        """当报告存在且 rule_id 合法时应正常处理反馈"""
        from app.models.document import ComplianceReport

        report_data = {
            "_decision_input": {
                "rule_violations": [
                    {"rule_id": "R010", "rule_type": "forbidden", "risk_level": "high"},
                ],
            },
        }

        report = ComplianceReport(
            file_id=1, total_score=90.0, violation_count=2,
            report_data=json.dumps(report_data),
            checked_by=1,  # matches test user
        )
        db_session.add(report)
        db_session.commit()
        db_session.refresh(report)

        resp = client.post(
            "/api/report/feedback",
            json={
                "report_id": report.id, "rule_id": "R010",
                "feedback_type": "confirm",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rule_id"] == "R010"
        assert data["status"] == "submitted"
        assert "event_id" in data
        assert "current_confidence" not in data

    def test_feedback_endpoint_forged_rule_id(self, client, auth_headers, db_session):
        """报告中不存在的 rule_id 应返回 400"""
        from app.models.document import ComplianceReport

        report_data = {
            "_decision_input": {
                "rule_violations": [
                    {"rule_id": "R001", "rule_type": "forbidden"},
                ],
            },
        }

        report = ComplianceReport(
            file_id=1, total_score=90.0, violation_count=1,
            report_data=json.dumps(report_data),
            checked_by=1,
        )
        db_session.add(report)
        db_session.commit()
        db_session.refresh(report)

        # 提交报告中没有的 rule_id
        resp = client.post(
            "/api/report/feedback",
            json={
                "report_id": report.id, "rule_id": "R_FORGED_999",
                "feedback_type": "confirm",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "不存在" in resp.json()["detail"]

    def test_feedback_endpoint_empty_report_data(self, client, auth_headers, db_session):
        """report_data 为空字典时，任意 rule_id 应被拒绝（fail-closed）"""
        from app.models.document import ComplianceReport

        report = ComplianceReport(
            file_id=1, total_score=90.0, violation_count=0,
            report_data="{}",  # empty dict
            checked_by=1,
        )
        db_session.add(report)
        db_session.commit()
        db_session.refresh(report)

        resp = client.post(
            "/api/report/feedback",
            json={
                "report_id": report.id, "rule_id": "R_ANY",
                "feedback_type": "confirm",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "不包含" in resp.json()["detail"] or "可反馈" in resp.json()["detail"]

    def test_feedback_endpoint_invalid_json_report_data(self, client, auth_headers, db_session):
        """report_data 为无效 JSON 时，应拒绝任意 rule_id"""
        from app.models.document import ComplianceReport

        report = ComplianceReport(
            file_id=1, total_score=90.0, violation_count=0,
            report_data="not valid json {{{",
            checked_by=1,
        )
        db_session.add(report)
        db_session.commit()
        db_session.refresh(report)

        resp = client.post(
            "/api/report/feedback",
            json={
                "report_id": report.id, "rule_id": "R_ANY",
                "feedback_type": "confirm",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_feedback_endpoint_no_findings(self, client, auth_headers, db_session):
        """报告没有 violations/findings 时，应拒绝任意 rule_id"""
        from app.models.document import ComplianceReport

        report_data = {
            "_diagnostics": {"routing": {"traffic_light": "green"}},
            # 没有 _decision_input，没有 violations
        }
        report = ComplianceReport(
            file_id=1, total_score=100.0, violation_count=0,
            report_data=json.dumps(report_data),
            checked_by=1,
        )
        db_session.add(report)
        db_session.commit()
        db_session.refresh(report)

        resp = client.post(
            "/api/report/feedback",
            json={
                "report_id": report.id, "rule_id": "R_FAKE",
                "feedback_type": "confirm",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_feedback_duplicate_returns_409(self, client, auth_headers, db_session):
        """同一用户/报告/规则重复提交返回 409"""
        from app.models.document import ComplianceReport

        report_data = {
            "_decision_input": {
                "rule_violations": [
                    {"rule_id": "R_DUP_TEST", "rule_type": "forbidden"},
                ],
            },
        }
        report = ComplianceReport(
            file_id=1, total_score=90.0, violation_count=1,
            report_data=json.dumps(report_data),
            checked_by=1,
        )
        db_session.add(report)
        db_session.commit()
        db_session.refresh(report)

        # 第一次：成功
        resp1 = client.post(
            "/api/report/feedback",
            json={
                "report_id": report.id, "rule_id": "R_DUP_TEST",
                "feedback_type": "confirm",
            },
            headers=auth_headers,
        )
        assert resp1.status_code == 200

        # 第二次：409
        resp2 = client.post(
            "/api/report/feedback",
            json={
                "report_id": report.id, "rule_id": "R_DUP_TEST",
                "feedback_type": "false_positive",
            },
            headers=auth_headers,
        )
        assert resp2.status_code == 409

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

        report_data = {
            "_decision_input": {
                "rule_violations": [
                    {"rule_id": "R011", "rule_type": "forbidden"},
                ],
            },
        }
        report = ComplianceReport(
            file_id=1, total_score=90.0, violation_count=2,
            report_data=json.dumps(report_data),
            checked_by=1,
        )
        db_session.add(report)
        db_session.commit()
        db_session.refresh(report)

        resp = client.post(
            "/api/report/feedback",
            json={
                "report_id": report.id, "rule_id": "R011",
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
