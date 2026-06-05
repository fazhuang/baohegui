"""参数倾向性检测测试"""
import pytest
from app.engine.parameter_bias import ParameterBiasDetector
from app.engine.shared_types import ParameterBiasResult


class TestParameterBiasDetector:
    """参数倾向性检测单元测试"""

    def test_detect_brand_lock(self):
        """检测品牌锁定：要求同品牌"""
        detector = ParameterBiasDetector()
        text = "汇聚交换机须与核心交换机为同一品牌。所有设备须同一品牌。"
        findings = detector._check_brand_lock_series(text, "technical_params")
        assert len(findings) > 0
        assert any("品牌" in f.pattern_name for f in findings)

    def test_detect_manufacturer_auth(self):
        """检测厂家授权锁"""
        detector = ParameterBiasDetector()
        text = "投标人须在投标时提供原厂授权函及原厂售后服务承诺函。"
        findings = detector._check_manufacturer_authorization(text, "qualification_requirements")
        assert len(findings) > 0
        assert any("厂家授权" in f.pattern_name or "授权" in f.description
                   for f in findings)

    def test_detect_detection_report_lock(self):
        """检测检测报告锁定"""
        detector = ParameterBiasDetector()
        text = "须提供国家建材检测中心出具的CMA检测报告。"
        findings = detector._check_detection_report_lock(text, "technical_params")
        assert len(findings) > 0

    def test_no_false_positive_on_normal_text(self):
        """正常文本不应触发误报"""
        detector = ParameterBiasDetector()
        text = "投标人应具备独立法人资格，具有有效的营业执照。"
        findings = detector._check_brand_lock_series(text, "qualification_requirements")
        brand_findings = [f for f in findings if "品牌" in f.pattern_name]
        assert len(brand_findings) == 0

    def test_run_full_detection(self):
        """完整检测流程"""
        detector = ParameterBiasDetector()
        sections = {
            "资格要求": "投标人须提供原厂授权函。须具备独立法人资格。",
            "技术要求": "所有产品须同一品牌。须提供CMA检测报告。",
            "评审办法": "综合评分法。",
        }
        result = detector.run(sections)
        assert isinstance(result, ParameterBiasResult)
        assert result.total_checks > 0
        assert len(result.findings) > 0
        assert result.risk_score >= 0

    def test_run_detection_empty_sections(self):
        """空章节不报错"""
        detector = ParameterBiasDetector()
        result = detector.run({})
        assert len(result.findings) == 0
        assert result.risk_score == 0.0

    def test_run_detection_normal_bid_document(self):
        """正常招标文件只触发少量或零发现"""
        detector = ParameterBiasDetector()
        sections = {
            "资格要求": "投标人应具备独立法人资格，具有有效营业执照。具备良好的商业信誉。",
            "技术要求": "产品应符合国家标准GB/T相关要求。技术参数详见附件。",
        }
        result = detector.run(sections)
        critical_and_high = [f for f in result.findings
                             if f.severity in ("critical", "high")]
        assert len(critical_and_high) == 0
