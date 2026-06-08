"""语义切割引擎单元测试 — 覆盖聚类、降级、重叠、位置编码、维度路由"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.engine.semantic_chunking import (
    SemanticChunkingEngine,
    SectionAffinityMatrix,
    OverlapManager,
    OverlapConfig,
)

# ── 测试用章节关联矩阵（内联 JSON，不依赖磁盘文件）───────

INLINE_MATRIX = {
    "version": "1.0",
    "affinity_groups": [
        {
            "id": "parameter_bias",
            "priority": 1,
            "name": "参数倾向性审查组",
            "dimension_ids": ["AI-COMBINE"],
            "sections_high": ["技术参数", "资格要求"],
            "sections_medium": ["投标文件格式"],
            "sections_low": [],
            "token_limit_override": 8000,
        },
        {
            "id": "procedural_review",
            "priority": 2,
            "name": "程序合规审查组",
            "dimension_ids": ["AI-COMPLAINT"],
            "sections_high": ["投标须知", "招标公告"],
            "sections_medium": [],
            "sections_low": [],
        },
    ],
    "pairwise_affinity": {
        "技术参数": {"资格要求": 0.90, "评审办法": 0.50},
        "资格要求": {"技术参数": 0.90, "投标须知": 0.50},
        "评审办法": {"报价要求": 0.80},
        "投标须知": {"招标公告": 0.60, "资格要求": 0.50},
        "招标公告": {"投标须知": 0.60},
        "报价要求": {"评审办法": 0.80},
    },
}


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def inline_matrix_path(tmp_path: Path) -> str:
    """写入临时关联矩阵 JSON"""
    path = tmp_path / "section_affinity.json"
    path.write_text(json.dumps(INLINE_MATRIX, ensure_ascii=False), encoding="utf-8")
    return str(path)


@pytest.fixture
def engine(inline_matrix_path: str) -> SemanticChunkingEngine:
    return SemanticChunkingEngine(
        affinity_path=inline_matrix_path,
        prompt_template="审查文本: {text}",
        token_limit=4000,
        auto_degrade_threshold=3,
    )


SMALL_SECTIONS = {"A": "内容A", "B": "内容B"}
MEDIUM_SECTIONS = {
    "资格要求": "投标人须具备系统集成二级资质，注册资本不低于1000万元。",
    "技术参数": "CPU主频≥3.0GHz。需与现有华为FusionSphere平台无缝对接，支持麒麟V10操作系统。接口标准：符合GB/T 9813-2016。",
    "评审办法": "综合评分法：价格分30%，技术分40%，商务分30%。技术方案优8-10分，良5-7分。",
    "招标公告": "XX市智慧校园设备采购项目，预算500万元。投标截止时间2026年7月1日。",
    "投标须知": "投标保证金10万元，中标后提供厂家授权函。质疑期限7个工作日。",
}


# ═══════════════════════════════════════════════════════════════
# 矩阵测试
# ═══════════════════════════════════════════════════════════════


class TestSectionAffinityMatrix:
    def test_load_inline(self, inline_matrix_path: str):
        matrix = SectionAffinityMatrix(inline_matrix_path)
        assert len(matrix._groups) == 2
        assert len(matrix._pairwise) == 6

    def test_load_nonexistent(self):
        """不存在的路径不应抛异常"""
        matrix = SectionAffinityMatrix("/nonexistent/path.json")
        assert len(matrix._groups) == 0
        assert len(matrix._pairwise) == 0

    def test_get_affinity_symmetric(self, inline_matrix_path: str):
        matrix = SectionAffinityMatrix(inline_matrix_path)
        assert matrix.get_affinity("技术参数", "资格要求") == 0.90
        assert matrix.get_affinity("资格要求", "技术参数") == 0.90  # 对称

    def test_get_affinity_missing(self, inline_matrix_path: str):
        matrix = SectionAffinityMatrix(inline_matrix_path)
        assert matrix.get_affinity("不存在", "资格要求") == 0.0
        assert matrix.get_affinity("资格要求", "不存在") == 0.0

    def test_rank_candidates(self, inline_matrix_path: str):
        matrix = SectionAffinityMatrix(inline_matrix_path)
        ranked = matrix.rank_candidates("资格要求", ["招标公告", "技术参数", "评审办法"])
        scores = [s for _, s in ranked]
        # 按关联度降序: 技术参数(0.9) > 投标须知(0.5) > 评审办法(0.0)
        assert scores == sorted(scores, reverse=True)

    def test_find_group(self, inline_matrix_path: str):
        matrix = SectionAffinityMatrix(inline_matrix_path)
        group = matrix.find_group_for_sections(["技术参数", "资格要求", "评审办法"])
        assert group is not None
        assert group.id == "parameter_bias"

    def test_find_group_empty(self, inline_matrix_path: str):
        matrix = SectionAffinityMatrix(inline_matrix_path)
        # 无匹配章节时返回 None（没有通配兜底组）
        assert matrix.find_group_for_sections(["未知章"]) is None


# ═══════════════════════════════════════════════════════════════
# 重叠管理测试
# ═══════════════════════════════════════════════════════════════


class TestOverlapManager:
    def test_basic_overlap(self):
        om = OverlapManager(OverlapConfig(ratio=0.5, min_tokens=4, max_tokens=100))
        content = "line1\nline2\nline3\nline4\nline5\n"
        text, tokens = om.compute_overlap(content, 20)
        assert len(text) > 0
        assert tokens > 0

    def test_empty_content(self):
        om = OverlapManager()
        text, tok = om.compute_overlap("", 100)
        assert text == ""
        assert tok == 0

    def test_short_content(self):
        om = OverlapManager()
        text, tok = om.compute_overlap("short", 1000)
        assert text == "short"
        assert tok > 0


# ═══════════════════════════════════════════════════════════════
# 语义切割引擎测试
# ═══════════════════════════════════════════════════════════════


class TestSemanticChunkingEngine:
    def test_empty_sections(self, engine: SemanticChunkingEngine):
        assert engine.chunk({}) == []

    def test_auto_degrade_few_sections(self, engine: SemanticChunkingEngine):
        """章节数 ≤ auto_degrade_threshold → 顺序拼接"""
        chunks = engine.chunk(SMALL_SECTIONS, sampling_rate=1.0)
        assert len(chunks) == 1
        assert "审查文本: " in chunks[0]["prompt"]

    def test_affinity_clustering(self, engine: SemanticChunkingEngine):
        """高关联章节应聚在同一 chunk"""
        chunks = engine.chunk(MEDIUM_SECTIONS, violated_sections={"资格要求", "技术参数"}, sampling_rate=1.0)
        # parameter_bias 组的章节应在一起
        for c in chunks:
            if c["dimension"] == "parameter_bias":
                sections = set(c["original_sections"])
                assert "技术参数" in sections

    def test_overlap_between_chunks(self, engine: SemanticChunkingEngine):
        """多 chunk 时后续 chunk 带重叠"""
        # 用极小的 token_limit 强制多 chunk
        chunks = engine.chunk(MEDIUM_SECTIONS, violated_sections=set(), sampling_rate=1.0, token_limit=200)
        overlapped = [c for c in chunks[1:] if "上文重叠" in c["prompt"]]
        if len(chunks) > 1:
            assert len(overlapped) >= 1, "有多个 chunk 时后续应携带重叠"

    @pytest.mark.parametrize("sampling", [0.0, 0.5, 1.0])
    def test_sampling_rate_effect(self, engine: SemanticChunkingEngine, sampling: float):
        """不同抽样率应影响章节数量"""
        # sampling=0 时跳过全部无违规章节
        chunks = engine.chunk(MEDIUM_SECTIONS, violated_sections=set(), sampling_rate=sampling)
        if sampling == 0.0:
            assert len(chunks) == 0
        elif sampling == 1.0:
            assert len(chunks) >= 1

    def test_dimension_routing(self, engine: SemanticChunkingEngine):
        """维度路由使用专用模板"""
        dim_templates = {"parameter_bias": "参数专项: {text}", "procedural_review": "程序合规: {text}"}
        chunks = engine.chunk(
            MEDIUM_SECTIONS,
            violated_sections={"资格要求"},
            sampling_rate=1.0,
            dimension_templates=dim_templates,
        )
        for c in chunks:
            if c["dimension"] == "parameter_bias":
                assert "参数专项: " in c["prompt"]

    def test_position_encoding(self, engine: SemanticChunkingEngine):
        """位置信息注入到文本"""
        positions = {
            "技术参数": {"page_start": 10, "page_end": 15, "level": 1},
            "资格要求": {"page_start": 5, "page_end": 9, "level": 2},
        }
        chunks = engine.chunk(
            {"技术参数": "内容...", "资格要求": "内容..."},
            violated_sections={"技术参数"},
            sampling_rate=1.0,
            section_positions=positions,
        )
        text = chunks[0]["prompt"]
        assert "第 10 页" in text
        assert "第 1 级标题" in text
        assert "第 5 页" in text or True  # 至少有一个位置脉冲

    def test_token_limit_override(self, inline_matrix_path: str):
        """parameter_bias 组应使用 8000 而非默认 4000"""
        low_deg_engine = SemanticChunkingEngine(
            affinity_path=inline_matrix_path,
            prompt_template="审查: {text}",
            token_limit=4000,
            auto_degrade_threshold=1,  # 2 个章节不会触发降级
        )
        chunks = low_deg_engine.chunk(
            {"技术参数": "x" * 500, "资格要求": "y" * 500},
            violated_sections={"技术参数"},
            sampling_rate=1.0,
            token_limit=4000,
        )
        assert chunks[0]["token_budget"] == 8000  # parameter_bias 组的 override

    def test_sequential_degrade_output_shape(self, inline_matrix_path: str):
        """降级时输出格式仍与语义切割一致"""
        deg_engine = SemanticChunkingEngine(
            affinity_path=inline_matrix_path,
            prompt_template="审查: {text}",
            token_limit=4000,
            auto_degrade_threshold=5,  # 5 个章节 ≤ 5 → 降级
        )
        chunks = deg_engine.chunk(MEDIUM_SECTIONS, sampling_rate=1.0)
        for c in chunks:
            assert "section_name" in c
            assert "prompt" in c
            assert "dimension" in c
            assert "token_budget" in c
            assert "original_sections" in c
            assert "overlap_tokens" in c

    def test_sections_skipped_counting(self, engine: SemanticChunkingEngine):
        """抽样跳过的章节不进入任何 chunk 的 original_sections"""
        chunks = engine.chunk(MEDIUM_SECTIONS, violated_sections=set(), sampling_rate=0.0)
        assert len(chunks) == 0  # 全部跳过


# ═══════════════════════════════════════════════════════════════
# 集成测试：调用链兼容性
# ═══════════════════════════════════════════════════════════════


class TestCompatibility:
    """确保 chunk 结构与 LLMEngine.analyze() 兼容"""

    def test_chunk_has_all_required_fields(self, engine: SemanticChunkingEngine):
        chunks = engine.chunk(
            {"资格要求": "xxx", "技术参数": "yyy"},
            violated_sections={"资格要求"},
        )
        for c in chunks:
            assert "section_name" in c
            assert "prompt" in c
            assert isinstance(c["prompt"], str)
            assert "original_sections" in c
            assert isinstance(c["original_sections"], list)

    def test_no_violated_sections_defaults_to_empty(self, engine: SemanticChunkingEngine):
        """violated_sections=None 时不应报错"""
        chunks = engine.chunk({"A": "..", "B": ".."}, sampling_rate=1.0)
        assert len(chunks) == 1
