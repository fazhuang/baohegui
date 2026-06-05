"""测试：大模型语义审查引擎（Mock 模式 + 工具函数）"""

from __future__ import annotations

import pytest

from app.engine.llm_engine import (
    LLMEngine,
    LLMEngineResult,
    LLMViolation,
    ModelRouter,
    _build_section_prompt,
    _extract_json,
    _extract_violated_sections,
    _parse_violations,
)
from app.engine.rule_engine import Violation

# ═══════════════════════════════════════════════════════════════
# _extract_json
# ═══════════════════════════════════════════════════════════════


class TestExtractJson:
    def test_plain_json(self):
        assert _extract_json('[{"type":"test"}]') == [{"type": "test"}]

    def test_json_in_code_block(self):
        result = _extract_json('```json\n[{"type":"test"}]\n```')
        assert result == [{"type": "test"}]

    def test_json_in_unspecified_block(self):
        result = _extract_json('```\n[{"type":"test"}]\n```')
        assert result == [{"type": "test"}]

    def test_json_embedded_in_text(self):
        text = '分析结果如下：\n[\n  {"type": "exclusivity"}\n]\n完毕'
        result = _extract_json(text)
        assert result == [{"type": "exclusivity"}]

    def test_invalid_input(self):
        assert _extract_json("不是 JSON") is None
        assert _extract_json("") is None

    def test_multiple_code_blocks(self):
        text = '```json\n[{"type":"a"}]\n```\n其他\n```\n[{"type":"b"}]\n```'
        result = _extract_json(text)
        assert result == [{"type": "a"}]  # 取第一个


# ═══════════════════════════════════════════════════════════════
# _extract_violated_sections
# ═══════════════════════════════════════════════════════════════


class TestExtractViolatedSections:
    def test_frombidden_location(self):
        vs = [
            Violation(
                rule_id="F1",
                rule_type="forbidden",
                description="",
                location="评审办法 ~第1行",
                weight=10,
            )
        ]
        result = _extract_violated_sections(vs, {"评审办法"})
        assert result == {"评审办法"}

    def test_keyword_required(self):
        vs = [
            Violation(
                rule_id="K1",
                rule_type="keyword_required",
                description="",
                location="应在《资格要求》中",
                weight=10,
            )
        ]
        result = _extract_violated_sections(vs, {"资格要求"})
        assert result == {"资格要求"}

    def test_chapter_required_ignored(self):
        vs = [
            Violation(rule_id="S1", rule_type="chapter_required", description="缺少章节", weight=10)
        ]
        result = _extract_violated_sections(vs, {"其他章节"})
        assert result == set()  # chapter_required 被忽略

    def test_section_not_in_document(self):
        vs = [
            Violation(
                rule_id="F1",
                rule_type="forbidden",
                description="",
                location="不存在章节 ~第1行",
                weight=10,
            )
        ]
        result = _extract_violated_sections(vs, {"实际章节"})
        assert result == set()

    def test_empty_input(self):
        assert _extract_violated_sections([], set()) == set()


# ═══════════════════════════════════════════════════════════════
# _build_section_prompt
# ═══════════════════════════════════════════════════════════════


class TestBuildSectionPrompt:
    def test_basic_chunking(self):
        sections = {"A": "内容", "B": "内容"}
        # 设为必检避免抽样跳过
        chunks, skipped = _build_section_prompt(
            sections,
            "模板:{text}",
            token_limit=99999,
            violated_sections={"A", "B"},
        )
        assert len(chunks) == 1
        assert skipped == 0

    def test_violated_sections_always_included(self):
        sections = {"A": "x" * 100, "B": "y" * 100}
        chunks, skipped = _build_section_prompt(
            sections,
            "{text}",
            token_limit=99999,
            violated_sections={"A"},
            sampling_rate=0.0,
        )
        # sampling_rate=0 → 所有非违规章节都被跳过
        assert "A" in chunks[0]["section_name"]
        assert skipped == 1  # B 被跳过

    def test_sampling_deterministic(self):
        sections = {"招标公告": "内容", "资格要求": "内容"}
        r1, _ = _build_section_prompt(sections, "{text}", 99999, set(), 0.3)
        r2, _ = _build_section_prompt(sections, "{text}", 99999, set(), 0.3)
        assert len(r1) == len(r2)

    def test_token_limit_enforced(self):
        """验证 token_limit 导致分片"""
        # 每个章节约 200 chars ≈ 400 tokens
        # 2 个章节=800＞limit=500 → 应分至少 2 片
        sections = {f"S{i}": "内容" * 100 for i in range(3)}
        chunks, _ = _build_section_prompt(
            sections,
            "{text}",
            token_limit=500,
            violated_sections={"S0", "S1", "S2"},
        )
        assert len(chunks) >= 2, f"预期分片≥2，实际{len(chunks)}"


# ═══════════════════════════════════════════════════════════════
# Mock 模式
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def mock_engine() -> LLMEngine:
    engine = LLMEngine()
    engine.mock_mode = True  # Force mock mode for testing
    return engine


class TestMockAnalyze:
    def test_clean_text_no_violations(self, mock_engine):
        import asyncio

        result = asyncio.run(mock_engine.analyze({"招标公告": "本项目采用公开招标方式。"}))
        assert isinstance(result, LLMEngineResult)
        # mock 模式无违规时返回空列表
        assert result.model_used == "mock"

    def test_local_enterprise_triggers_exclusivity(self, mock_engine):
        import asyncio

        result = asyncio.run(mock_engine.analyze({"资格要求": "投标人必须为本市注册企业。"}))
        types = {v.type for v in result.violations}
        assert "exclusivity" in types

    def test_specified_brand_triggers_exclusivity(self, mock_engine):
        import asyncio

        result = asyncio.run(mock_engine.analyze({"评审办法": "指定品牌XXXX。"}))
        types = {v.type for v in result.violations}
        assert "exclusivity" in types

    def test_high_risk_level_propagated(self, mock_engine):
        import asyncio

        result = asyncio.run(mock_engine.analyze({"资格要求": "本市注册企业，指定品牌产品。"}))
        for v in result.violations:
            assert v.risk_level in ("high", "medium", "low")

    def test_score_calculation(self, mock_engine):
        import asyncio

        result = asyncio.run(mock_engine.analyze({"资格要求": "指定品牌。本地注册。"}))
        assert result.total_score < 100
        assert 0 <= result.total_score <= 100


# ═══════════════════════════════════════════════════════════════
# LLMViolation 数据模型
# ═══════════════════════════════════════════════════════════════


class TestLLMViolation:
    def test_valid_types(self):
        for t in ("exclusivity", "bias", "hidden_barrier", "ambiguity", "high_risk"):
            v = LLMViolation(type=t, section="", text="", risk_level="high")
            assert v.type == t

    def test_default_risk_level(self):
        v = LLMViolation(type="bias", section="", text="")
        assert v.risk_level == "medium"

    def test_default_weight(self):
        v = LLMViolation(type="bias", section="", text="")
        assert v.weight == 10.0

    def test_invalid_type(self):
        with pytest.raises(Exception):
            LLMViolation(type="invalid", section="", text="")

    def test_evidence_field_default(self):
        """v3 新增：evidence 字段默认值为空字符串"""
        v = LLMViolation(type="bias", section="", text="")
        assert v.evidence == ""

    def test_consequence_field_default(self):
        """v3 新增：consequence 字段默认值为空字符串"""
        v = LLMViolation(type="bias", section="", text="")
        assert v.consequence == ""

    def test_confidence_field_default(self):
        """v3 新增：confidence 字段默认值为 0.0"""
        v = LLMViolation(type="bias", section="", text="")
        assert v.confidence == 0.0

    def test_new_fields_populated(self):
        """v3 新增：新字段可以正常赋值"""
        v = LLMViolation(
            type="exclusivity",
            section="资格要求",
            text="要求投标人必须为本市注册企业",
            risk_level="high",
            evidence="原文：投标人必须为本市注册企业",
            consequence="若不修正，外地供应商无法参与，将引发质疑投诉",
            confidence=0.92,
        )
        assert v.evidence == "原文：投标人必须为本市注册企业"
        assert v.consequence == "若不修正，外地供应商无法参与，将引发质疑投诉"
        assert v.confidence == 0.92


# ═══════════════════════════════════════════════════════════════
# _parse_violations — v3 字段解析
# ═══════════════════════════════════════════════════════════════


class TestParseViolations:
    def test_parse_v2_format_compat(self):
        """v2 格式的 JSON 仍可正常解析"""
        raw = [
            {
                "type": "exclusivity",
                "section": "资格要求",
                "text": "指定品牌产品",
                "risk_level": "high",
                "reason": "排他性条款",
                "suggestion": "改为同等性能",
                "law_ref": "《政府采购法》第二十二条",
            }
        ]
        violations = _parse_violations(raw)
        assert len(violations) == 1
        v = violations[0]
        assert v.type == "exclusivity"
        assert v.evidence == ""  # v2 格式无此字段，取默认值
        assert v.consequence == ""  # v2 格式无此字段，取默认值
        assert v.confidence == 0.0  # v2 格式无此字段，取默认值

    def test_parse_v3_format(self):
        """v3 格式的 JSON 包含新字段"""
        raw = [
            {
                "type": "exclusivity",
                "section": "资格要求",
                "text": "指定品牌产品",
                "risk_level": "high",
                "reason": "排他性条款",
                "suggestion": "改为同等性能",
                "law_ref": "《政府采购法》第二十二条",
                "evidence": "原文明确指定了XX品牌",
                "consequence": "平台将拦截并退回，供应商可依法投诉",
                "confidence": 0.95,
            }
        ]
        violations = _parse_violations(raw)
        assert len(violations) == 1
        v = violations[0]
        assert v.evidence == "原文明确指定了XX品牌"
        assert v.consequence == "平台将拦截并退回，供应商可依法投诉"
        assert v.confidence == 0.95

    def test_parse_evidence_text_alias(self):
        """evidence_text 字段自动映射为 evidence"""
        raw = [
            {
                "type": "bias",
                "section": "",
                "text": "test",
                "risk_level": "medium",
                "evidence_text": "逐字引用的原文",
                "confidence": 0.8,
            }
        ]
        violations = _parse_violations(raw)
        assert violations[0].evidence == "逐字引用的原文"

    def test_parse_basis_alias(self):
        """basis 字段自动映射为 law_ref"""
        raw = [
            {
                "type": "bias",
                "section": "",
                "text": "test",
                "risk_level": "medium",
                "basis": "《政府采购法》第五条",
            }
        ]
        violations = _parse_violations(raw)
        assert violations[0].law_ref == "《政府采购法》第五条"

    def test_parse_confidence_invalid(self):
        """confidence 为非数值时回退为 0.0"""
        raw = [
            {
                "type": "bias",
                "section": "",
                "text": "test",
                "risk_level": "medium",
                "confidence": "high",
            }
        ]
        violations = _parse_violations(raw)
        assert violations[0].confidence == 0.0

    def test_parse_empty_list(self):
        """空列表返回空"""
        assert _parse_violations([]) == []


# ═══════════════════════════════════════════════════════════════
# ModelRouter — 多模型路由
# ═══════════════════════════════════════════════════════════════


class TestModelRouter:
    """多模型路由测试"""

    def test_load_routing_config(self):
        import os
        # 解析相对于项目根目录的路径
        config_path = "rules/prompts/model_routing.json"
        router = ModelRouter(config_path)
        assert router.default_model == "deepseek-chat"
        assert len(router.dimension_routing) == 17

    def test_route_known_dimension(self):
        router = ModelRouter("rules/prompts/model_routing.json")
        config = router.route("AI-BRAND")
        assert config is not None
        assert "provider" in config

    def test_route_known_dimension_returns_proper_config(self):
        """验证已知维度的配置包含必要字段"""
        router = ModelRouter("rules/prompts/model_routing.json")
        config = router.route("AI-STD")
        assert config is not None
        # qwen-plus 被指派给 AI-STD
        assert config.get("model") == "qwen-plus"
        assert config.get("provider") == "openai_compatible"

    def test_route_unknown_dimension_falls_back(self):
        router = ModelRouter("rules/prompts/model_routing.json")
        config = router.route("SOME-UNKNOWN-DIM")
        assert config is not None  # falls back to default
        assert "provider" in config

    def test_missing_config_file_uses_defaults(self, tmp_path):
        p = tmp_path / "nonexistent.json"
        router = ModelRouter(str(p))
        # Should not crash, should have empty routing
        config = router.route("AI-BRAND")
        assert config is not None
        assert "provider" in config

    def test_get_api_key_from_env(self, monkeypatch):
        """测试 API key 通过环境变量解析"""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-ds-key")
        router = ModelRouter("rules/prompts/model_routing.json")
        config = router.model_configs.get("deepseek-chat", {})
        key = router.get_api_key(config)
        assert key == "test-ds-key"

    def test_get_api_key_empty_when_not_set(self, monkeypatch):
        """环境变量未设置时返回空字符串"""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("QWEN_API_KEY", raising=False)
        router = ModelRouter("rules/prompts/model_routing.json")
        config = router.model_configs.get("deepseek-chat", {})
        key = router.get_api_key(config)
        assert key == ""

