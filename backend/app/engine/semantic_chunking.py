"""语义感知 Chunking 引擎

将文档章节按语义关联度聚类到同一 chunk，配合滑动窗口重叠和维度路由，
解决跨章节违规漏检和边界截断问题。

使用方式::
    engine = SemanticChunkingEngine(
        affinity_path="rules/section_affinity.json",
        prompt_template=compliance_prompt,
        token_limit=6000,
    )
    chunks = engine.chunk(sections, violated_sections)
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════


@dataclass
class AffinityGroup:
    """关联组定义"""
    id: str
    priority: int
    name: str
    dimension_ids: list[str]
    sections_high: list[str]
    sections_medium: list[str]
    sections_low: list[str]
    token_limit_override: int | None = None


@dataclass
class OverlapConfig:
    """滑动窗口重叠参数"""
    ratio: float = 0.15
    min_tokens: int = 200
    max_tokens: int = 800


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

TOKEN_EST_RATIO = 2.0  # 1 汉字 ≈ 2 tokens


def _estimate_tokens(text: str) -> int:
    """粗略估算 Token 数"""
    return math.ceil(len(text) * TOKEN_EST_RATIO)


def _build_section_header(section_name: str) -> str:
    return f"=== {section_name} ===\n"


# ═══════════════════════════════════════════════════════════════
# 章节关联矩阵
# ═══════════════════════════════════════════════════════════════


class SectionAffinityMatrix:
    """加载和查询章节关联矩阵"""

    def __init__(self, path: str | Path | None = None):
        self._pairwise: dict[str, dict[str, float]] = {}
        self._groups: list[AffinityGroup] = []
        if path:
            self.load(path)

    # ── 加载 ────────────────────────────────────────────────

    def load(self, path: str | Path) -> bool:
        """加载关联矩阵 JSON。失败时保留内存中默认值并记录警告。"""
        p = Path(path)
        if not p.exists():
            logger.warning("章节关联矩阵不存在: %s", p)
            return False
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("章节关联矩阵加载失败: %s", e)
            return False

        self._pairwise = data.get("pairwise_affinity", {})
        self._groups = [
            AffinityGroup(
                id=g["id"],
                priority=g.get("priority", 99),
                name=g.get("name", g["id"]),
                dimension_ids=g.get("dimension_ids", []),
                sections_high=g.get("sections_high", []),
                sections_medium=g.get("sections_medium", []),
                sections_low=g.get("sections_low", []),
                token_limit_override=g.get("token_limit_override"),
            )
            for g in data.get("affinity_groups", [])
        ]
        logger.info(
            "章节关联矩阵就绪: %d 组, %d 对关联",
            len(self._groups), len(self._pairwise),
        )
        return True

    def reload(self, path: str | Path | None = None) -> bool:
        """热加载"""
        if path:
            return self.load(path)
        return False

    # ── 查询 ────────────────────────────────────────────────

    def get_affinity(self, a: str, b: str) -> float:
        """返回两个章节类型的关联度 [0, 1]，双向查询"""
        row = self._pairwise.get(a)
        if row is not None and b in row:
            return row[b]
        row = self._pairwise.get(b)
        if row is not None and a in row:
            return row[a]
        return 0.0

    def rank_candidates(self, seed: str, candidates: list[str]) -> list[tuple[str, float]]:
        """按与 seed 的关联度降序排列候选"""
        scored = [(c, self.get_affinity(seed, c)) for c in candidates]
        scored.sort(key=lambda x: -x[1])
        return scored

    def find_group_for_sections(self, section_names: list[str]) -> AffinityGroup | None:
        """根据章节列表找到最匹配的关联组"""
        best_group: AffinityGroup | None = None
        best_score = 0
        for g in self._groups:
            score = sum(
                3 if s in g.sections_high
                else 2 if s in g.sections_medium
                else 1 if s in g.sections_low
                else 0
                for s in section_names
            )
            if score > best_score:
                best_score = score
                best_group = g
        return best_group

    def resolve_token_limit(self, section_names: list[str], default_limit: int) -> int:
        """根据匹配的关联组确定 Token 预算"""
        group = self.find_group_for_sections(section_names)
        if group and group.token_limit_override:
            return max(default_limit, group.token_limit_override)
        return default_limit


# ═══════════════════════════════════════════════════════════════
# 滑动窗口重叠管理
# ═══════════════════════════════════════════════════════════════


class OverlapManager:
    """管理相邻 chunk 间的内容重叠"""

    def __init__(self, config: OverlapConfig | None = None):
        self.config = config or OverlapConfig()

    def compute_overlap(self, prev_content: str, max_tokens: int) -> tuple[str, int]:
        """从 prev_content 尾部截取合理重叠文本

        从换行处断开，避免截断句子。

        Returns:
            (overlap_text, actual_tokens)
        """
        target_chars = math.ceil(
            min(
                max(self.config.min_tokens, max_tokens * self.config.ratio),
                self.config.max_tokens,
            )
            / TOKEN_EST_RATIO
        )
        if target_chars <= 0 or not prev_content:
            return "", 0

        if len(prev_content) <= target_chars:
            return prev_content, _estimate_tokens(prev_content)

        # 尾部截取 target_chars 字符，尽量从换行处断开
        tail = prev_content[-target_chars:]
        newline_pos = tail.find("\n")
        if 0 < newline_pos < target_chars // 2:
            tail = tail[newline_pos + 1:]
        return tail, _estimate_tokens(tail)


# ═══════════════════════════════════════════════════════════════
# 主引擎
# ═══════════════════════════════════════════════════════════════


class SemanticChunkingEngine:
    """语义感知 Chunking 引擎

    Args:
        affinity_path: 章节关联矩阵 JSON 路径（None = 仅做顺序拼接）
        prompt_template: 默认 Prompt 模板（含 {text} 占位符）
        token_limit: 默认单次调用 Token 上限
        overlap_config: 滑动窗口重叠配置
        auto_degrade_threshold: 章节数 ≤ 此值时回退到顺序拼接
    """

    def __init__(
        self,
        affinity_path: str | Path | None = None,
        prompt_template: str = "",
        token_limit: int = 6000,
        overlap_config: OverlapConfig | None = None,
        auto_degrade_threshold: int = 5,
    ):
        self.matrix = SectionAffinityMatrix(affinity_path) if affinity_path else SectionAffinityMatrix()
        self._prompt_template = prompt_template
        self.default_token_limit = token_limit
        self.overlap = OverlapManager(overlap_config)
        self.auto_degrade_threshold = auto_degrade_threshold

        # 运行时缓存
        self._section_texts: dict[str, str] = {}
        self._section_positions: dict[str, dict] = {}
        self._dimension_templates: dict[str, str] = {}

    # ── 公开入口 ───────────────────────────────────────────

    def chunk(
        self,
        sections: dict[str, str],
        violated_sections: set[str] | None = None,
        sampling_rate: float = 0.3,
        prompt_template: str | None = None,
        token_limit: int | None = None,
        section_positions: dict[str, dict] | None = None,
        dimension_templates: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """将文档章节按语义聚类为 chunks

        Args:
            sections:          章节名 → 内容
            violated_sections: 规则引擎已查出的章节名集合
            sampling_rate:     无违规章节抽样比例 (0~1)
            prompt_template:   Prompt 模板（覆盖初始化时传入的，作为降级后备）
            token_limit:       Token 上限（覆盖默认）
            section_positions: 可选 {section_type: {page_start, page_end, level}}
            dimension_templates: 可选 {dimension_id: template_text}
                               用于按维度选择不同 Prompt

        Returns:
            与 LLMEngine 兼容的 chunk 列表
        """
        if not sections:
            return []

        self._section_texts = dict(sections)
        self._section_positions = section_positions or {}
        self._dimension_templates = dimension_templates or {}
        tmpl = prompt_template or self._prompt_template
        limit = token_limit or self.default_token_limit
        violated = violated_sections or set()
        sec_names = list(sections.keys())

        # ── 自动降级：章节太少 → 顺序拼接 ─────────────
        if len(sec_names) <= self.auto_degrade_threshold:
            logger.info(
                "语义切割降级: 章节数 %d ≤ %d, 使用顺序拼接",
                len(sec_names), self.auto_degrade_threshold,
            )
            return self._sequential_chunks(sec_names, tmpl, limit, violated, sampling_rate)

        # ── Step 1: 选取种子 ─────────────────────────────
        seeds = self._select_seeds(sec_names, violated, sampling_rate)
        if not seeds:
            return []

        # ── Step 2: 亲和度聚类 ──────────────────────────
        raw_chunks = self._cluster(seeds, limit)

        # ── Step 3: 未分配章节兜底 ──────────────────────
        assigned = {s for c in raw_chunks for s in c["sections"]}
        unassigned = [s for s in sec_names if s not in assigned]
        if unassigned:
            logger.info("未分配章节归入综合组: %s", unassigned)
            raw_chunks.append({"sections": unassigned})

        # ── Step 4: 构建 Prompt + 重叠 ──────────────────
        return self._build_chunks(raw_chunks, tmpl, limit)

    # ── 种子选择 ───────────────────────────────────────────

    def _select_seeds(
        self,
        sec_names: list[str],
        violated: set[str],
        sampling_rate: float,
    ) -> list[str]:
        """选出要送入 LLM 的章节作为聚类种子

        违规章节 100% 必检；无违规章节按 sampling_rate 确定性抽样。
        返回按 (违规优先, 关联组优先级) 排序的列表。
        """
        seeds: list[tuple[int, int, str]] = []

        for name in sec_names:
            if name in violated:
                seeds.append((0, 0, name))  # 最高优先级
            else:
                seed = hash(name) & 0x7FFFFFFF
                if (seed % 1000) / 1000.0 > sampling_rate:
                    logger.debug("抽样跳过章节 [%s]", name)
                    continue
                group = self.matrix.find_group_for_sections([name])
                priority = group.priority if group else 99
                seeds.append((1, priority, name))

        seeds.sort(key=lambda x: (x[0], x[1]))
        return [s[2] for s in seeds]

    # ── 贪心聚类 ───────────────────────────────────────────

    def _cluster(
        self, seeds: list[str], token_limit: int,
    ) -> list[dict[str, Any]]:
        """基于关联度贪心聚类

        每一步从 seeds 取一个未被分配的章节作为新 chunk 的种子，
        按关联度从高到低尝试加入其他未分配章节。
        """
        assigned: set[str] = set()
        chunks: list[dict[str, Any]] = []

        for seed in seeds:
            if seed in assigned:
                continue

            current_sections = [seed]
            current_tokens = _estimate_tokens(self._text_for_section(seed))
            assigned.add(seed)

            remaining = [s for s in self._section_texts if s not in assigned]
            candidates = self.matrix.rank_candidates(seed, remaining)
            budget = token_limit

            for cand, aff in candidates:
                if cand in assigned:
                    continue
                cand_tokens = _estimate_tokens(self._text_for_section(cand))
                needed = current_tokens + cand_tokens

                if needed <= budget:
                    current_sections.append(cand)
                    current_tokens = needed
                    assigned.add(cand)
                elif aff >= 0.8:
                    # 高关联度：扩展 budget +50% 以包含
                    expanded = int(budget * 1.5)
                    if current_tokens + cand_tokens <= expanded:
                        budget = expanded
                        current_sections.append(cand)
                        current_tokens += cand_tokens
                        assigned.add(cand)
                        logger.debug(
                            "高关联度(%.2f)扩展 budget %d→%d 以包含 [%s]",
                            aff, token_limit, expanded, cand,
                        )

            chunks.append({"sections": current_sections})

        return chunks

    # ── 维度路由 ───────────────────────────────────────────

    def _resolve_dimension(
        self, section_names: list[str], default_limit: int,
    ) -> tuple[str, int]:
        """根据章节组成决定审查维度和 Token 预算"""
        group = self.matrix.find_group_for_sections(section_names)
        if group:
            return group.id, group.token_limit_override or default_limit
        return "general", default_limit

    # ── 文本构建 ───────────────────────────────────────────

    def _text_for_section(self, name: str) -> str:
        """获取单章节带标题和位置编码的文本"""
        content = self._section_texts.get(name, "")
        pos = self._section_positions.get(name)
        if pos:
            parts = [f"=== {name} ==="]
            page = pos.get("page_start") or pos.get("page")
            level = pos.get("level")
            ctx = []
            if page:
                ctx.append(f"第 {page} 页")
            if level:
                ctx.append(f"第 {level} 级标题")
            if ctx:
                parts.insert(1, f"【{', '.join(ctx)}】")
            parts.append(content)
            parts.append("")
            return "\n".join(parts) + "\n\n"
        return f"=== {name} ===\n{content}\n\n"

    def _build_section_text(self, section_names: list[str]) -> str:
        """拼接多章节文本"""
        return "".join(self._text_for_section(n) for n in section_names)

    def _build_chunks(
        self,
        raw_chunks: list[dict[str, Any]],
        prompt_template: str,
        token_limit: int,
    ) -> list[dict[str, Any]]:
        """将原始聚类结果组装为带 Prompt 和重叠的最终 chunk 列表"""
        result: list[dict[str, Any]] = []
        prev_content = ""

        for raw in raw_chunks:
            text = self._build_section_text(raw["sections"])
            dim, t_budget = self._resolve_dimension(raw["sections"], token_limit)

            # 按维度选择 Prompt 模板
            dim_tmpl = self._dimension_templates.get(dim, prompt_template)
            full_prompt = dim_tmpl.replace("{text}", text) if dim_tmpl else text

            # 滑动窗口重叠
            overlap_text, overlap_tok = "", 0
            if prev_content:
                overlap_text, overlap_tok = self.overlap.compute_overlap(prev_content, t_budget)
                if overlap_text:
                    full_prompt = full_prompt.replace(
                        "{text}",
                        f"【上文重叠】\n{overlap_text}\n\n{text}",
                    ) if "{text}" in full_prompt else f"【上文重叠】\n{overlap_text}\n\n{full_prompt}"

            section_name = " + ".join(raw["sections"])

            result.append({
                "section_name": section_name,
                "prompt": full_prompt,
                "dimension": dim,
                "token_budget": t_budget,
                "original_sections": raw["sections"],
                "overlap_tokens": overlap_tok,
            })

            prev_content = text

        _log_chunks(result)
        return result

    # ── 顺序拼接降级 ───────────────────────────────────────

    def _sequential_chunks(
        self,
        sec_names: list[str],
        prompt_template: str,
        token_limit: int,
        violated: set[str],
        sampling_rate: float,
    ) -> list[dict[str, Any]]:
        """降级方案：按文档顺序拼接（等价于原 _build_section_prompt 逻辑）

        用于章节数 ≤ auto_degrade_threshold 时自动回退。
        """
        chunks: list[dict[str, Any]] = []
        current_names: list[str] = []
        current_text_parts: list[str] = []
        current_size = 0

        for name in sec_names:
            is_violated = name in violated
            if not is_violated:
                seed = hash(name) & 0x7FFFFFFF
                if (seed % 1000) / 1000.0 > sampling_rate:
                    continue

            text_block = self._text_for_section(name)
            block_tokens = _estimate_tokens(text_block)

            if current_size + block_tokens > token_limit and current_names:
                combined = "".join(current_text_parts)
                cname = " + ".join(current_names)
                chunks.append({
                    "section_name": cname,
                    "prompt": prompt_template.replace("{text}", combined),
                    "dimension": "general",
                    "token_budget": token_limit,
                    "original_sections": list(current_names),
                    "overlap_tokens": 0,
                })
                current_names = []
                current_text_parts = []
                current_size = 0

            current_names.append(name)
            current_text_parts.append(text_block)
            current_size += block_tokens

        if current_names:
            combined = "".join(current_text_parts)
            cname = " + ".join(current_names)
            chunks.append({
                "section_name": cname,
                "prompt": prompt_template.replace("{text}", combined),
                "dimension": "general",
                "token_budget": token_limit,
                "original_sections": list(current_names),
                "overlap_tokens": 0,
            })

        return chunks


# ── 日志辅助 ───────────────────────────────────────────────


def _log_chunks(chunks: list[dict]) -> None:
    if not chunks:
        return
    lines = [f"  语义切割: {len(chunks)} 个 chunk"]
    for i, c in enumerate(chunks):
        name = c.get("section_name", "?")
        budget = c.get("token_budget", "?")
        dim = c.get("dimension", "?")
        overlap = c.get("overlap_tokens", 0)
        tag = f" +{overlap}t" if overlap else ""
        lines.append(f"    [{i}] {dim} ~{budget}tok 「{name}」{tag}")
    logger.info("\n".join(lines))


# ── 便捷函数 ───────────────────────────────────────────────


def chunk_sections(
    sections: dict[str, str],
    violated_sections: set[str] | None = None,
    prompt_template: str = "",
    token_limit: int = 4000,
    affinity_path: str | Path | None = None,
    sampling_rate: float = 0.3,
    **kwargs,
) -> list[dict[str, Any]]:
    """便捷入口：一次调用完成语义切割"""
    engine = SemanticChunkingEngine(
        affinity_path=affinity_path,
        prompt_template=prompt_template,
        token_limit=token_limit,
    )
    return engine.chunk(
        sections=sections,
        violated_sections=violated_sections,
        sampling_rate=sampling_rate,
    )
