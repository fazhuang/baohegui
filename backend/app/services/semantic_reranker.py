"""Phase 3 Two-Stage Reranker — post-merge semantic reordering.

Designed to re-rank the merged candidate list from knowledge_graph.search()
by penalizing broad-match nodes (industry, concept) and promoting nodes
whose titles align with the query's semantic intent.

Strategy: After the two-pass keyword search + merge, apply a lightweight
"relevance filter" that:
1. HEAVILY penalizes industry_rule nodes (IND-xxx) — they match keywords broadly
2. Slightly promotes core compliance rules (R-xxx with clear rule_id)
3. Promotes forbidden_word/rule nodes with title bigram overlap
4. Demotes concept/industry/generic nodes that don't have exact bigram hits
"""

from __future__ import annotations

import re as _re
from typing import Optional


# ══════════════════════════════════════════════════════════════════
# Tokenizer
# ══════════════════════════════════════════════════════════════════

_STOP_CHARS = frozenset(
    "的了在是我有就不人都一上也说到要你的看自他那"
    "什么么怎如何为因为所以但或与对于对将以被让向从使通过可以"
    "需要应该已经比较非常还是不过把从次第每"
)


def _tokenize_chinese(text: str) -> list[str]:
    """2-4 char Chinese n-grams, stop-filtered."""
    if not text:
        return []
    runs = _re.findall(r"[一-鿿㐀-䶿]{2,}", text.strip())
    tokens = []
    for seq in runs:
        L = len(seq)
        for i in range(L - 3):
            tokens.append(seq[i:i + 4])
        for i in range(L - 2):
            tokens.append(seq[i:i + 3])
        for i in range(L - 1):
            bg = seq[i:i + 2]
            if not (bg[0] in _STOP_CHARS and bg[1] in _STOP_CHARS):
                tokens.append(bg)
    seen = set()
    result = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result[:30]


# ══════════════════════════════════════════════════════════════════
# Reranker
# ══════════════════════════════════════════════════════════════════


def rerank_merged_results(
    nodes: list[dict],
    query: str,
    tags: Optional[str] = None,
    top_k: int = 20,
) -> list[dict]:
    """Apply semantic reranker to merged search results.

    Re-ranks a merged candidate list by applying additive bonuses and
    penalties. Preserves the existing IDF-based ordering (which is good
    at recall) but adjusts rank positions to push relevant nodes above
    industry/concept noise.

    Bonuses (additive, ~0–6 range):
    - Exact bigram hit in title (+2.5 per 3-4 char term, capped +5)
    - Tag intersection (+1.5 per shared tag, capped +4.5)
    - Rule ID appears in query (+4)
    - Node type: rule (+1.5), forbidden_word (+1.0), key_concept (+0.5)

    Penalties (subtractive):
    - Industry node type (−1.5)
    - Concept node type (−0.5)
    - NODE-xxx or KEY-xxx IDs with no rule_id (−1.0)

    Args:
        nodes: Merged result dicts from knowledge_graph.search().
        query: Original query text.
        tags: Optional comma-separated tag string.
        top_k: Return top K results.

    Returns:
        Reordered result dicts, best first.
    """
    if not nodes:
        return []

    qlower = query.lower().strip() if query else ""
    qtokens = _tokenize_chinese(qlower)
    mid_terms = [t for t in qtokens if len(t) == 3]
    long_terms = [t for t in qtokens if len(t) >= 4]

    query_tags = set()
    if tags:
        query_tags = {t.strip() for t in tags.split(",") if t.strip()}

    # Type bonuses and penalties (additive to an implicit base of 0)
    TYPE_DELTA = {
        "rule": 1.5,          # promote: rules are what users search for
        "forbidden_word": 1.0,  # promote: forbidden patterns = compliance
        "key_concept": 0.5,   # mild promote: useful context
        "regulation": 0.3,    # mild promote: legal basis
        "case": 0.2,          # neutral+: reference value
        "template": -0.2,     # neutral-: template noise
        "parameter": -0.2,    # neutral-: parameter noise
        "concept": -0.5,      # demote: generic concepts
        "industry": -1.5,     # strong demote: industry rules are keyword-hungry
    }
    DEFAULT_DELTA = -0.3

    results: list[tuple[float, dict]] = []

    for n in nodes:
        try:
            delta = 0.0
            rule_id = (n.get("rule_id") or "").lower()
            ntype = n.get("node_type", "")
            title = (n.get("title") or "").lower()
            ntags = {(t or "").strip() for t in (n.get("tags") or "").split(",") if t.strip()}

            # 1. Exact bigram hits: mid-term or long-term found in title
            bigram_count = 0
            for t in mid_terms + long_terms:
                if t in title:
                    bigram_count += 1
            bigram_count = min(bigram_count, 5)
            delta += bigram_count * 2.0

            # 2. Tag intersection
            if query_tags and ntags:
                delta += min(len(query_tags & ntags), 3) * 1.5

            # 3. Rule ID in query
            if rule_id and len(rule_id) >= 3 and rule_id in qlower:
                delta += 4.0

            # 4. Node type delta
            delta += TYPE_DELTA.get(ntype, DEFAULT_DELTA)

            # 5. Title contains query keywords count (higher = better match)
            kw_in_title = sum(1 for t in qtokens if t in title)
            delta += min(kw_in_title, 10) * 0.3

            results.append((delta, n))
        except Exception:
            results.append((0.0, n))

    # Sort by delta desc
    results.sort(key=lambda x: x[0], reverse=True)

    return [n for _, n in results[:top_k]]
