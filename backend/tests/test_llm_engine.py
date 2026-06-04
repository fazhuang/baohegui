"""测试：大模型语义审查引擎（Mock 模式 + 工具函数）"""

from __future__ import annotations

import pytest

from app.engine.llm_engine import (
    LLMEngine,
    LLMViolation,
    LLMEngineResult,
    _extract_json,
    _build_section_prompt,
    _extract_violated_sections,
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
        text = "分析结果如下：\n[\n  {\"type\": \"exclusivity\"}\n]\n完毕"
        result = _extract_json(text)
        assert result == [{"type": "exclusivity"}]

    def test_invalid_input(self):
        assert _extract_json("不是 JSON") is None
        assert _extract_json("") is None

    def test_multiple_code_blocks(self):
        text = "```json\n[{\"type\":\"a\"}]\n```\n其他\n```\n[{\"type\":\"b\"}]\n```"
        result = _extract_json(text)
        assert result == [{"type": "a"}]  # 取第一个


# ═══════════════════════════════════════════════════════════════
# _extract_violated_sections
# ═══════════════════════════════════════════════════════════════

class TestExtractViolatedSections:
    def test_frombidden_location(self):
        vs = [Violation(rule_id="F1", rule_type="forbidden",
                        description="", location="评审办法 ~第1行", weight=10)]
        result = _extract_violated_sections(vs, {"评审办法"})
        assert result == {"评审办法"}

    def test_keyword_required(self):
        vs = [Violation(rule_id="K1", rule_type="keyword_required",
                        description="", location="应在《资格要求》中", weight=10)]
        result = _extract_violated_sections(vs, {"资格要求"})
        assert result == {"资格要求"}

    def test_chapter_required_ignored(self):
        vs = [Violation(rule_id="S1", rule_type="chapter_required",
                        description="缺少章节", weight=10)]
        result = _extract_violated_sections(vs, {"其他章节"})
        assert result == set()  # chapter_required 被忽略

    def test_section_not_in_document(self):
        vs = [Violation(rule_id="F1", rule_type="forbidden",
                        description="", location="不存在章节 ~第1行", weight=10)]
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
            sections, "模板:{text}", token_limit=99999,
            violated_sections={"A", "B"},
        )
        assert len(chunks) == 1
        assert skipped == 0

    def test_violated_sections_always_included(self):
        sections = {"A": "x" * 100, "B": "y" * 100}
        chunks, skipped = _build_section_prompt(
            sections, "{text}", token_limit=99999,
            violated_sections={"A"}, sampling_rate=0.0,
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
            sections, "{text}", token_limit=500,
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
        result = asyncio.run(
            mock_engine.analyze({"招标公告": "本项目采用公开招标方式。"})
        )
        assert isinstance(result, LLMEngineResult)
        # mock 模式无违规时返回空列表
        assert result.model_used == "mock"

    def test_local_enterprise_triggers_exclusivity(self, mock_engine):
        import asyncio
        result = asyncio.run(
            mock_engine.analyze({"资格要求": "投标人必须为本市注册企业。"})
        )
        types = {v.type for v in result.violations}
        assert "exclusivity" in types

    def test_specified_brand_triggers_exclusivity(self, mock_engine):
        import asyncio
        result = asyncio.run(
            mock_engine.analyze({"评审办法": "指定品牌XXXX。"})
        )
        types = {v.type for v in result.violations}
        assert "exclusivity" in types

    def test_high_risk_level_propagated(self, mock_engine):
        import asyncio
        result = asyncio.run(
            mock_engine.analyze({"资格要求": "本市注册企业，指定品牌产品。"})
        )
        for v in result.violations:
            assert v.risk_level in ("high", "medium", "low")

    def test_score_calculation(self, mock_engine):
        import asyncio
        result = asyncio.run(
            mock_engine.analyze({"资格要求": "指定品牌。本地注册。"})
        )
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
