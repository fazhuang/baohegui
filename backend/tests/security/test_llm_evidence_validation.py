"""安全测试 — LLM evidence 校验（强化版）

覆盖：
- validate_llm_evidence 逐字命中 full_text
- 不存在 evidence 降级 needs_review + validation_error
- 有效 law_ref + 不存在 evidence → needs_review
- law_ref 命中规则库成立
- law_ref 不命中规则库降级
"""

import pytest

from app.engine.fusion import validate_llm_evidence, _validate_law_ref, _build_rule_db_snapshot
from app.engine.llm_engine import LLMEngineResult, LLMViolation


class TestLLMEvidenceValidation:
    """LLM 证据链校验"""

    # ── law_ref 校验 ──

    def test_validate_valid_law_ref(self):
        assert _validate_law_ref("《政府采购法》第五条")
        assert _validate_law_ref("政府采购法实施条例第二十条")
        assert _validate_law_ref("招标投标法 第10条")
        assert _validate_law_ref("政府采购促进中小企业发展管理办法")

    def test_validate_invalid_law_ref(self):
        assert not _validate_law_ref("")
        assert not _validate_law_ref("   ")
        assert not _validate_law_ref(None)
        # 仅含"政府采购法"但无法对应 rule_db 条目时也不应通过
        # （rule_db 现在由 _build_rule_db_snapshot 构建）

    def test_validate_made_up_law(self):
        assert not _validate_law_ref("《供应商管理办法》第100条")
        assert not _validate_law_ref("《内部规定第X章》")
        assert not _validate_law_ref("《虚构法律第一百条》")

    # ── 逐字命中 full_text ──

    def test_evidence_must_match_full_text(self):
        """evidence/text 必须在 full_text 中逐字命中"""
        full_text = "本项目采用公开招标方式。预算金额为500万元。"
        llm_result = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity",
                    section="招标公告",
                    text="本项目采用公开招标方式",  # 精确匹配
                    risk_level="high",
                    reason="测试",
                    law_ref="《政府采购法》第五条",
                ),
            ],
            total_score=90.0,
        )
        validated = validate_llm_evidence(llm_result, full_text)
        # 精确匹配 + 有效 law_ref → 不应降级
        assert validated.violations[0].validation_error is None

    def test_nonexistent_evidence_downgraded(self):
        """不存在的 evidence 应被降级并设置 validation_error"""
        full_text = "本项目采用公开招标方式。预算金额为500万元。"
        llm_result = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity",
                    section="招标公告",
                    text="本项目强制要求投标人必须是央企",  # 不在 full_text 中
                    risk_level="high",
                    reason="排他性条款",
                    law_ref="《政府采购法实施条例》第二十条",  # 有效法规引用
                ),
            ],
            total_score=90.0,
        )
        validated = validate_llm_evidence(llm_result, full_text)
        v = validated.violations[0]
        # 证据不在原文中 → 降级
        assert v.validation_error is not None, (
            "不存在的 evidence 应该有 validation_error"
        )
        assert v.requires_human_review is True

    def test_valid_law_ref_and_nonexistent_evidence_needs_review(self):
        """有效 law_ref + 不存在 evidence → 仍降级 needs_review"""
        full_text = "采购方式：公开招标。技术要求详见附件。"
        llm_result = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity",
                    section="资格要求",
                    text="须提供厂家唯一授权证明文件原件",  # 不存在
                    risk_level="high",
                    reason="排他性条款",
                    law_ref="《政府采购法实施条例》第二十条",  # 有效
                ),
            ],
            total_score=90.0,
        )
        validated = validate_llm_evidence(llm_result, full_text)
        v = validated.violations[0]
        assert v.validation_error is not None
        assert v.requires_human_review is True

    def test_invalid_law_ref_downgraded(self):
        """无效 law_ref → 降级 needs_review"""
        full_text = "本项目指定使用XX品牌产品，不接受替代品牌。"
        llm_result = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity",
                    section="资格要求",
                    text="指定使用XX品牌产品",  # 存在
                    risk_level="high",
                    reason="品牌锁定",
                    law_ref="《虚构法律第一百条》",  # 不存在于规则库
                ),
            ],
            total_score=90.0,
        )
        validated = validate_llm_evidence(llm_result, full_text)
        v = validated.violations[0]
        assert v.validation_error is not None
        assert v.requires_human_review is True

    def test_no_evidence_and_no_law_ref_downgraded(self):
        """无 evidence 且无 law_ref → 双重降级"""
        full_text = "test"
        llm_result = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="hidden_barrier",
                    section="评审办法",
                    text="",  # 空 evidence
                    risk_level="high",
                    reason="无证据的推测",
                    law_ref="",  # 空 law_ref
                ),
            ],
            total_score=90.0,
        )
        validated = validate_llm_evidence(llm_result, full_text)
        v = validated.violations[0]
        assert v.validation_error is not None
        assert v.requires_human_review is True

    def test_rule_db_snapshot_contains_references(self):
        """_build_rule_db_snapshot 应包含真实规则库中的法规名称"""
        db = _build_rule_db_snapshot()
        assert len(db) > 0, "规则库快照不应为空"
        assert any("政府采购法" in entry for entry in db), "应包含政府采购法引用"


class TestLawRefAgainstRuleDB:
    """law_ref 必须命中规则库/法规库的真实条目"""

    def test_law_ref_must_match_rule_db_entry(self):
        """
        仅含"政府采购法"关键词但未命中规则库条目，不应通过。
        重点：不应仅因为含"政府采购法"就通过；
        如果 rule_db 中只有"政府采购法"而非"政府采购法管理细则"，应 False。
        """
        rule_db = _build_rule_db_snapshot()

        # ① 正确的、在规则库中实际存在的条目 → 应返回 True
        assert _validate_law_ref("《政府采购法》第五条")

        # ② 一个既不在 rule_db 中，又只包含“政府采购法”关键词的参考 → 应返回 False
        # 这里我们使用一个明确不在快照里的引用，确保它被视作无效
        assert not _validate_law_ref("《政府采购法管理细则》第X条")

        # ③ 另一个不存在的虚构法规 → 必须 False
        assert not _validate_law_ref("《虚构法律》第一条")