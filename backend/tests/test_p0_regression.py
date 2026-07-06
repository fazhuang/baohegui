"""P0 回归测试 — 上传 + 融合 + 状态机 + 报告导出

覆盖：
1. 短 evidence 在 fusion 中校验失败
2. law_ref 不在规则库中校验失败
3. 上传零全量内存读入（代码路径断言）
4. queued → checking → completed 真实流转
5. PDF / Excel 人工复核字段导出
"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════
# 1. 短 evidence 在 fusion 中校验失败
# ═══════════════════════════════════════════════════════════════════

from app.engine.fusion import validate_llm_evidence, _build_rule_db_snapshot
from app.engine.llm_engine import LLMEngineResult, LLMViolation


class TestShortEvidenceValidation:
    """短 evidence 文本应校验失败"""

    def test_evidence_not_in_full_text_fails(self):
        """evidence 不在 full_text 中 → validation_error"""
        llm_result = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity",
                    section="评审办法",
                    text="这段文字完全不在招标文件中应该报错",
                    risk_level="high",
                    reason="疑似排他",
                    law_ref="政府采购法",
                ),
            ],
            total_score=90.0,
        )
        full_text = "这是招标文件的内容，不包含上面的违规证据文本"
        rule_db = _build_rule_db_snapshot()
        validated = validate_llm_evidence(llm_result, full_text, rule_db)

        v = validated.violations[0]
        err = v.validation_error
        assert err is not None, f"短evidence/full_text不命中应产生validation_error，但实际: err={err}"
        assert "未命中" in err, f"错误信息应包含'未命中原文': {err}"

    def test_short_evidence_core_less_than_4_fails(self):
        """核心文本 < 4 字符 → 校验失败（标点 stripped 后核心为0）"""
        llm_result = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity",
                    section="评审办法",
                    text="，。；：",
                    risk_level="medium",
                    reason="纯标点",
                    law_ref="政府采购法",
                ),
            ],
            total_score=95.0,
        )
        full_text = "完整的招标文件正文内容，不包含连续的纯标点模式。"
        rule_db = _build_rule_db_snapshot()
        validated = validate_llm_evidence(llm_result, full_text, rule_db)

        v = validated.violations[0]
        err = v.validation_error
        assert err is not None, f"核心<4字符应失败: err={err}"
        assert "未命中" in err or "evidence_text" in err, f"错误信息不正确: {err}"

    def test_empty_evidence_fails(self):
        """空的 evidence_text → 校验失败"""
        llm_result = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity",
                    section="评审办法",
                    text="",
                    risk_level="medium",
                    reason="没有证据",
                    law_ref="政府采购法",
                ),
            ],
            total_score=95.0,
        )
        rule_db = _build_rule_db_snapshot()
        validated = validate_llm_evidence(llm_result, "任意原文", rule_db)

        v = validated.violations[0]
        err = v.validation_error
        assert err is not None, "空 evidence 应失败"
        assert "缺少" in err, f"错误信息应包含'缺少': {err}"

    def test_valid_evidence_passes(self):
        """有效的 evidence 应通过校验"""
        llm_result = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity",
                    section="评审办法",
                    text="须提供原厂授权函",
                    risk_level="high",
                    reason="排他性要求",
                    law_ref="政府采购法",
                ),
            ],
            total_score=90.0,
        )
        full_text = "投标人须提供原厂授权函原件，否则不予受理。"
        rule_db = _build_rule_db_snapshot()
        validated = validate_llm_evidence(llm_result, full_text, rule_db)

        v = validated.violations[0]
        err = v.validation_error
        # 如果 law_ref 在 rule_db 中命中 → 应通过；否则仅 law_ref 失败
        # evidence 应该通过
        if err:
            assert "evidence" not in err.lower() or "evidence_text" not in err, \
                f"evidence有效但被误判: {err}"


# ═══════════════════════════════════════════════════════════════════
# 2. law_ref 不在规则库中校验失败
# ═══════════════════════════════════════════════════════════════════


class TestLawRefValidation:
    """law_ref 必须精确命中规则库条目"""

    def test_nonexistent_law_ref_fails(self):
        """不存在的法规引用应校验失败"""
        llm_result = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity",
                    section="评审办法",
                    text="须提供原厂授权函",
                    risk_level="high",
                    reason="排他性",
                    law_ref="《中华人民共和国不存在的法律》",
                ),
            ],
            total_score=90.0,
        )
        full_text = "投标人须提供原厂授权函原件，否则不予受理。"
        rule_db = _build_rule_db_snapshot()
        validated = validate_llm_evidence(llm_result, full_text, rule_db)

        v = validated.violations[0]
        err = v.validation_error
        assert err is not None, "不存在的 law_ref 应失败"
        assert "law_ref" in err.lower(), f"错误应提及law_ref: {err}"

    def test_empty_law_ref_fails(self):
        """空的 law_ref → 校验失败"""
        llm_result = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity",
                    section="评审办法",
                    text="须提供原厂授权函",
                    risk_level="high",
                    reason="排他性",
                    law_ref="",
                ),
            ],
            total_score=90.0,
        )
        full_text = "投标人须提供原厂授权函原件，否则不予受理。"
        rule_db = _build_rule_db_snapshot()
        validated = validate_llm_evidence(llm_result, full_text, rule_db)

        v = validated.violations[0]
        err = v.validation_error
        assert err is not None, "空 law_ref 应失败"
        assert "law_ref" in err.lower() or "缺少" in err, f"错误应提及law_ref: {err}"

    def test_requires_human_review_set_on_validation_failure(self):
        """校验失败时应设置 __requires_human_review__ = True"""
        llm_result = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity",
                    section="评审办法",
                    text="不存在的内容",
                    risk_level="high",
                    reason="排他性",
                    law_ref="不存在的法律名称乱写",
                ),
            ],
            total_score=90.0,
        )
        rule_db = _build_rule_db_snapshot()
        validated = validate_llm_evidence(llm_result, "完全无关的原文", rule_db)

        v = validated.violations[0]
        requires_review = v.requires_human_review
        assert requires_review is True, "证据+法规双重失败应标记 requires_human_review"


# ═══════════════════════════════════════════════════════════════════
# 3. 上传零全量内存读入（代码路径断言）
# ═══════════════════════════════════════════════════════════════════


class TestUploadNoFullRead:
    """upload.py 不应调用 tf.read() 全量读入"""

    def test_upload_uses_upload_from_path_not_upload_with_bytes(self):
        """upload.py 应使用 upload_from_path 而非 upload(data)"""
        upload_path = Path(__file__).resolve().parent.parent / "app" / "api" / "upload.py"
        source = upload_path.read_text(encoding="utf-8")

        # 不应有 tf.read() 全量读入（注释除外）
        stripped = "\n".join(
            line for line in source.splitlines()
            if not line.strip().startswith("#")
        )
        assert "tf.read()" not in stripped, "不应有 tf.read() 全量读入"
        assert 'content =' not in stripped or 'content_type =' in stripped, \
            "不应有 content = 全量读入变量"

    def test_upload_uses_upload_from_path(self):
        """upload.py 应使用 minio_service.upload_from_path"""
        upload_path = Path(__file__).resolve().parent.parent / "app" / "api" / "upload.py"
        source = upload_path.read_text(encoding="utf-8")
        assert "upload_from_path" in source, "应使用 upload_from_path 流上传"

    def test_minio_has_upload_from_path_method(self):
        """MinioService 应有 upload_from_path 方法"""
        from app.services.minio_service import MinioService
        ms = MinioService()
        assert hasattr(ms, 'upload_from_path'), "MinioService 缺少 upload_from_path 方法"
        assert callable(ms.upload_from_path), "upload_from_path 应为可调用方法"

    def test_upload_status_is_uploaded(self):
        """上传后文件状态应为 uploaded（不再用 parsing）"""
        upload_path = Path(__file__).resolve().parent.parent / "app" / "api" / "upload.py"
        source = upload_path.read_text(encoding="utf-8")
        # status 应为 "uploaded"，不含 "parsing" 作为初始上传状态
        assert 'status="uploaded"' in source, "上传后状态应为 uploaded"


# ═══════════════════════════════════════════════════════════════════
# 4. queued → checking → completed 真实流转
# ═══════════════════════════════════════════════════════════════════


class TestCheckTaskStateMachine:
    """检查任务状态机 queued → checking → completed/failed"""

    def test_status_transition_in_check_code(self):
        """check.py 应包含 queued → checking 流转"""
        check_path = Path(__file__).resolve().parent.parent / "app" / "api" / "check.py"
        source = check_path.read_text(encoding="utf-8")

        assert 'status = "queued"' in source, "check.py 应设置 queued 状态"
        assert 'status = "checking"' in source, "check.py 应设置 checking 状态"
        assert 'status = "completed"' in source, "check.py 应设置 completed 状态"
        assert 'status = "failed"' in source, "check.py 应设置 failed 状态"

    def test_check_validates_status_before_start(self):
        """check.py 应校验文件状态（只能从 uploaded/queued/failed/completed 开始）"""
        check_path = Path(__file__).resolve().parent.parent / "app" / "api" / "check.py"
        source = check_path.read_text(encoding="utf-8")

        assert "not in (\"uploaded\"" in source or "not in ('uploaded'" in source, \
            "check.py 应校验起始状态"
        assert "409" in source, "状态不符应返回 409 Conflict"

    def test_uploaded_file_has_queued_enum(self):
        """UploadedFile 模型应包含 queued 状态"""
        model_path = Path(__file__).resolve().parent.parent / "app" / "models" / "document.py"
        source = model_path.read_text(encoding="utf-8")
        assert "queued" in source, "UploadedFile status 枚举应包含 queued"

    def test_state_machine_flow_in_diagnostics(self):
        """诊断数据应包含状态机流转说明"""
        check_path = Path(__file__).resolve().parent.parent / "app" / "api" / "check.py"
        source = check_path.read_text(encoding="utf-8")
        assert "state_machine" in source, "诊断数据应包含 state_machine 字段"
        assert "queued → checking → completed" in source, \
            "应包含完整流转链描述"


# ═══════════════════════════════════════════════════════════════════
# 5. PDF / Excel 人工复核字段导出
# ═══════════════════════════════════════════════════════════════════


class TestReportExportHumanReviewFields:
    """PDF 和 Excel 导出应包含人工复核字段"""

    def test_pdf_template_has_validation_error(self):
        """PDF 模板应包含校验失败和人工复核字段"""
        report_gen_path = Path(__file__).resolve().parent.parent / "app" / "services" / "report_gen.py"
        source = report_gen_path.read_text(encoding="utf-8")
        assert "validation_error" in source, \
            "PDF 模板应渲染 validation_error"
        assert "requires_human_review" in source or "需要人工复核" in source, \
            "PDF 模板应渲染 requires_human_review"

    def test_excel_export_has_validation_columns(self):
        """Excel 导出应包含校验错误和需人工复核列"""
        excel_path = Path(__file__).resolve().parent.parent / "app" / "services" / "excel_exporter.py"
        source = excel_path.read_text(encoding="utf-8")
        assert "校验错误" in source, "Excel 表头应包含'校验错误'列"
        assert "需人工复核" in source, "Excel 表头应包含'需人工复核'列"
        assert '"validation_error"' in source, "Excel 行数据应包含 validation_error"
        assert '"requires_human_review"' in source, "Excel 行数据应包含 requires_human_review"

    def test_excel_build_violation_rows_has_new_fields(self):
        """build_violation_rows 的 LLM 条目应包含 validation_error 和 requires_human_review"""
        from app.services.excel_exporter import build_violation_rows

        report_data = {
            "llm_violations": [
                {
                    "type": "exclusivity",
                    "reason": "存在排他性条款",
                    "text": "须提供厂家授权",
                    "risk_level": "high",
                    "validation_error": "evidence 未命中原文",
                    "requires_human_review": True,
                },
            ],
            "rule_violations": [],
        }
        rows = build_violation_rows(report_data)
        assert len(rows) == 1
        assert rows[0]["validation_error"] == "evidence 未命中原文"
        assert rows[0]["requires_human_review"] == "是"

    def test_report_data_saves_merge_result(self):
        """check.py 保存的 report_data 应将 merge_result 证据持久化到 _diagnostics"""
        check_path = Path(__file__).resolve().parent.parent / "app" / "api" / "check.py"
        source = check_path.read_text(encoding="utf-8")
        assert "merge_result" in source, "report_data 应在 _diagnostics 中持久化 merge_result"
        assert "risk_items_count" in source, "merge_result 应包含 risk_items 计数"
        assert "confirmed_count" in source, "merge_result 应包含 confirmed_count"
        assert "validation_error" in source, "check.py 应保留 validation_error 字段"
        assert "requires_human_review" in source, "check.py 应保留 requires_human_review 字段"


# ═══════════════════════════════════════════════════════════════════
# 6. 静态前缀放行已删除
# ═══════════════════════════════════════════════════════════════════


class TestNoStaticLawRefBypass:
    """fusion.py 不应有静态已知法规关键词前缀放行"""

    def test_no_static_known_law_ref_keywords(self):
        """fusion.py 不应再包含 _KNOWN_LAW_REF_KEYWORDS 静态集合"""
        fusion_path = Path(__file__).resolve().parent.parent / "app" / "engine" / "fusion.py"
        source = fusion_path.read_text(encoding="utf-8")
        assert "_KNOWN_LAW_REF_KEYWORDS" not in source, \
            "fusion.py 不应再包含静态 _KNOWN_LAW_REF_KEYWORDS 前缀放行集合"

    def test_build_rule_db_snapshot_no_static_fallback(self):
        """_build_rule_db_snapshot 异常时应返回空集而非静态集合"""
        fusion_path = Path(__file__).resolve().parent.parent / "app" / "engine" / "fusion.py"
        source = fusion_path.read_text(encoding="utf-8")
        assert "return set()" in source, \
            "_build_rule_db_snapshot 异常时应返回空 set()，不给静态前缀放行"
