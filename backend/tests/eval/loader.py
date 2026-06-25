"""Phase 3 检索评测数据加载器"""

import json
from pathlib import Path
from typing import Optional

from .metrics import EvalQuery, RelevantDoc

_EVAL_DIR = Path(__file__).resolve().parent


def load_queries(path: Optional[Path] = None, version: str = "v1") -> list[EvalQuery]:
    """Load annotated eval queries from JSON.

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
            # Hard negatives can be specified by title or id
            if isinstance(hd, str):
                hard_negatives.append(RelevantDoc(
                    id=hd,  # title as id for string-only negatives
                    rel_type="",
                    relevance=0,
                    title=hd,
                    is_hard_negative=True,
                ))
            else:
                hard_negatives.append(RelevantDoc(
                    id=hd["id"],
                    rel_type=hd.get("rel_type", ""),
                    relevance=0,
                    title=hd.get("title", ""),
                    is_hard_negative=True,
                ))

        jurisdiction = qd.get("jurisdiction")
        search_keywords = qd.get("search_keywords", [])

        eq = EvalQuery(
            query_id=qd["query_id"],
            query_text=qd["query_text"],
            relevant_docs=relevant,
            hard_negatives=hard_negatives,
            node_type=qd.get("node_type"),
            jurisdiction=jurisdiction,
            tags=qd.get("tags", []),
            expected_regulations=qd.get("expected_regulations", []),
            expected_cases=qd.get("expected_cases", []),
        )
        eq.search_keywords = search_keywords  # type: ignore
        queries.append(eq)

    return queries


def load_queries_as_dict(path: Optional[Path] = None) -> list[dict]:
    """Load raw query dicts (for parameterized tests)."""
    if path is None:
        path = _EVAL_DIR / "queries_v1.json"

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("queries", [])
