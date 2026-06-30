"""原文全文比对工具

P0 强校验：将 LLM 生成的 evidence 文本与原始文档全文进行逐字/模糊匹配。
提供三种匹配策略：
1. 精确匹配（子串命中，O(n+m)）
2. Levenshtein 模糊匹配（编辑距离 ≤2 或相似度 ≥0.85）
3. 滑动窗口最佳片段返回（返回原文中最匹配的片段及相似度）

用作 validate_llm_evidence() 的底层引擎，替代原来的纯 substring in 检查。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── 配置常量 ─────────────────────────────────────────────
MAX_EDIT_DISTANCE = 2         # 编辑距离绝对阈值（P1: 3→2，收紧误匹配窗口）
MIN_SIMILARITY_RATIO = 0.85   # 相似度比率阈值（P1: 0.80→0.85，需更强匹配置信度）
MIN_EVIDENCE_LENGTH = 8       # P1: 最短 evidence 长度（<8 字符拒绝模糊匹配，要求精确命中）
WINDOW_MARGIN = 20            # 返回片段时前后扩展的字符数


# ═══════════════════════════════════════════════════════════════
# Levenshtein 编辑距离（DP）
# ═══════════════════════════════════════════════════════════════

def levenshtein_distance(s1: str, s2: str) -> int:
    """计算两个字符串的 Levenshtein 编辑距离（DP，O(n*m)）。

    短字符串（<50 字符）直接全量 DP；长字符串使用优化版。
    """
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)

    # 确保 s1 是较短的（优化内存）
    if len(s1) > len(s2):
        s1, s2 = s2, s1

    m, n = len(s1), len(s2)
    # 使用两行滚动数组优化空间
    prev = list(range(n + 1))
    curr = [0] * (n + 1)

    for i in range(1, m + 1):
        curr[0] = i
        for j in range(1, n + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,       # 删除
                curr[j - 1] + 1,   # 插入
                prev[j - 1] + cost,  # 替换
            )
        prev, curr = curr, prev

    return prev[n]


def text_similarity_ratio(s1: str, s2: str) -> float:
    """基于编辑距离的文本相似度比率 (0.0-1.0)。

    使用公式: 1 - edit_distance / max(len(s1), len(s2))
    """
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    dist = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))
    return round(1.0 - dist / max_len, 4)


# ═══════════════════════════════════════════════════════════════
# 文本预处理
# ═══════════════════════════════════════════════════════════════

def normalize_for_matching(text: str) -> str:
    """标准化文本用于比对：小写 + 去空白规范化 + 统一标点。

    保留中文字符和基本标点结构，移除多余的空白。
    """
    import re
    # 小写
    t = text.lower()
    # 统一全角/半角
    t = t.replace("　", " ")          # 全角空格
    t = t.replace("（", "(").replace("）", ")")
    t = t.replace("“", '"').replace("”", '"')
    t = t.replace("‘", "'").replace("’", "'")
    t = t.replace("，", ",").replace("、", ",")
    t = t.replace("；", ";").replace("：", ":")
    # 折叠连续空白为单个空格
    t = re.sub(r"\s+", " ", t)
    # 去除首尾空白
    return t.strip()


# ═══════════════════════════════════════════════════════════════
# 比对引擎
# ═══════════════════════════════════════════════════════════════

class EvidenceMatcher:
    """LLM 证据文本与原文全文比对器"""

    @staticmethod
    def exact_match(evidence: str, full_text: str) -> Optional[dict]:
        """精确子串匹配。

        Returns:
            None 如果未命中；dict with matched_text, offset_start, offset_end 如果命中。
        """
        if not evidence or not full_text:
            return None

        evidence_norm = normalize_for_matching(evidence)
        full_norm = normalize_for_matching(full_text)

        idx = full_norm.find(evidence_norm)
        if idx >= 0:
            # 返回原文中的实际片段（而非标准化版本）
            end = idx + len(evidence_norm)
            return {
                "matched_text": full_norm[idx:end],
                "offset_start": idx,
                "offset_end": end,
                "match_method": "exact",
                "similarity": 1.0,
            }
        return None

    @staticmethod
    def fuzzy_match(
        evidence: str,
        full_text: str,
        max_edit: int = MAX_EDIT_DISTANCE,
        min_similarity: float = MIN_SIMILARITY_RATIO,
    ) -> Optional[dict]:
        """Levenshtein 模糊匹配：在全文上滑动窗口，找到最佳匹配片段。

        策略：
        1. 将 evidence 标准化
        2. 在标准化后的 full_text 上以 evidence 长度 ± margin 的窗口滑动
        3. 计算每个窗口与 evidence 的编辑距离
        4. 选出最佳（相似度最高且满足阈值）的片段

        Returns:
            None 如果无满足阈值的匹配；
            dict with matched_text, offset_start, offset_end, similarity, edit_distance, match_method="fuzzy"
        """
        if not evidence or not full_text:
            return None

        ev_norm = normalize_for_matching(evidence)
        full_norm = normalize_for_matching(full_text)
        ev_len = len(ev_norm)

        if ev_len < MIN_EVIDENCE_LENGTH:
            # P1: 短 evidence 不可靠，要求精确匹配（阈值从 4 提升到 8）
            logger.debug("evidence 长度=%d < %d，降级为精确匹配", ev_len, MIN_EVIDENCE_LENGTH)
            return EvidenceMatcher.exact_match(evidence, full_text)

        best: Optional[dict] = None

        # 窗口大小：evidence 长度 ± 30%
        window_range = max(2, int(ev_len * 0.3))
        step = max(1, ev_len // 4)  # 步长：25% 覆盖

        for window_len in range(
            max(4, ev_len - window_range),
            ev_len + window_range + 1,
        ):
            for start in range(0, max(1, len(full_norm) - window_len + 1), step):
                window = full_norm[start:start + window_len]
                dist = levenshtein_distance(ev_norm, window)
                similarity = 1.0 - dist / max(ev_len, len(window))

                if similarity >= min_similarity and dist <= max_edit:
                    if best is None or similarity > best["similarity"]:
                        best = {
                            "matched_text": window[:200],  # 截断过长文本
                            "offset_start": start,
                            "offset_end": start + len(window),
                            "similarity": round(similarity, 4),
                            "edit_distance": dist,
                            "match_method": "fuzzy",
                        }

        return best

    @staticmethod
    def best_match(
        evidence: str,
        full_text: str,
        max_edit: int = MAX_EDIT_DISTANCE,
        min_similarity: float = MIN_SIMILARITY_RATIO,
    ) -> dict:
        """综合匹配：先精确，后模糊，返回最佳结果。

        Returns:
            dict with:
            - matched: bool 是否匹配成功
            - method: "exact" | "fuzzy" | "none"
            - matched_text: 匹配到的原文片段
            - similarity: 相似度 (0.0-1.0)
            - edit_distance: 编辑距离（仅 fuzzy）
            - offset_start / offset_end: 位置（如果有）
        """
        # 策略 1：精确匹配
        exact = EvidenceMatcher.exact_match(evidence, full_text)
        if exact:
            exact["matched"] = True
            return exact

        # 策略 2：模糊匹配
        fuzzy = EvidenceMatcher.fuzzy_match(
            evidence, full_text, max_edit=max_edit, min_similarity=min_similarity,
        )
        if fuzzy:
            fuzzy["matched"] = True
            return fuzzy

        return {"matched": False, "method": "none", "similarity": 0.0}


# ── 便捷函数 ─────────────────────────────────────────────

evidence_matcher = EvidenceMatcher()


def match_evidence(
    evidence_text: str,
    full_text: str,
    require_exact: bool = False,
) -> dict:
    """便捷入口：匹配 evidence 到原文。

    Args:
        evidence_text: LLM 输出的证据文本
        full_text: 文档原文
        require_exact: True 时跳过模糊匹配，仅做精确匹配

    Returns:
        同 EvidenceMatcher.best_match()
    """
    if require_exact:
        result = EvidenceMatcher.exact_match(evidence_text, full_text)
        if result:
            result["matched"] = True
            return result
        return {"matched": False, "method": "none", "similarity": 0.0}
    return EvidenceMatcher.best_match(evidence_text, full_text)
