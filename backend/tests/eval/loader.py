"""Phase 3 检索评测数据加载器

查询加载后可通过 canonical_id_map 将标题/名称映射到 KG canonical ID，
以便指标计算和硬负样本检测。

Canonical ID 规则（与 retrievers._canonical_id 一致）：
- rule 节点：rule_id（如 "R001"）
- 非 rule 节点：title 前缀匹配 + NODE-{id}（用于硬负检测）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .metrics import EvalQuery, RelevantDoc

_EVAL_DIR = Path(__file__).resolve().parent


def load_queries(path: Optional[Path] = None, version: str = "v1") -> list[EvalQuery]:
    """Load annotated eval queries from JSON.

    search_keywords 已从数据集剥离。检索器只能使用 query_text + tags
    + node_type + jurisdiction 作为输入。

    Args:
        path: Optional explicit path to queries JSON.
        version: Which version to load if path not given (v1, v2, etc.)

    Returns:
        List of EvalQuery objects ready for evaluation.
    """
    if path is None:
        path = _EVAL_DIR / f"queries_{version}.json"

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    queries: list[EvalQuery] = []
    for qd in data.get("queries", []):
        relevant = []
        for rd in qd.get("relevant", []):
            relevant.append(RelevantDoc(
                id=rd["id"],
                rel_type=rd.get("rel_type", "rule"),
                relevance=rd.get("relevance", 1),
                title=rd.get("title", ""),
            ))

        hard_negatives = []
        for hd in qd.get("hard_negatives", []):
            # Hard negatives can be specified by title or object
            # Title-only form is resolved against canonical_id_map at eval time
            if isinstance(hd, str):
                hard_negatives.append(RelevantDoc(
                    id=hd,  # title — resolved via canonical_id_map at eval time
                    rel_type="case",
                    relevance=0,
                    title=hd,
                    is_hard_negative=True,
                ))
            else:
                hard_negatives.append(RelevantDoc(
                    id=hd["id"],
                    rel_type=hd.get("rel_type", "case"),
                    relevance=0,
                    title=hd.get("title", ""),
                    is_hard_negative=True,
                ))

        eq = EvalQuery(
            query_id=qd["query_id"],
            query_text=qd["query_text"],
            relevant_docs=relevant,
            hard_negatives=hard_negatives,
            node_type=qd.get("node_type"),
            jurisdiction=qd.get("jurisdiction"),
            tags=qd.get("tags", []),
            expected_regulations=qd.get("expected_regulations", []),
            expected_cases=qd.get("expected_cases", []),
        )
        queries.append(eq)

    return queries


def load_queries_as_dict(path: Optional[Path] = None) -> list[dict]:
    """Load raw query dicts (for parameterized tests)."""
    if path is None:
        path = _EVAL_DIR / "queries_v1.json"

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("queries", [])
