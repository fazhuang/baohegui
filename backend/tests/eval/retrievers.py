"""Phase 3 检索评估套件 — 连接评测框架与知识图谱服务

提供 baseline（现有关键词搜索）和 optimized（PostgreSQL 增强）检索器，
以及 RAG on/off 对照。

检索器返回的 RetrievedDoc.id 统一为 rule_id 字符串（如 "R001"），
以匹配评测数据集中的 relevant_docs 标注。

检索策略：
- 中文分词提取关键词 → 多词 OR ILIKE（解决自然语言查询 0 召回问题）
- Tag 检索：标签精确匹配（用于困难查询）
- RAG 图遍历：rule → regulation/case 关联
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.services.knowledge_graph import knowledge_graph
from .metrics import EvalQuery, RetrievedDoc, EvalRun, run_retrieval_eval, format_eval_report
from .loader import load_queries
from .keywords import extract_keywords


def _canonical_id(r: dict) -> str:
    """Return string canonical ID: rule_id preferred, else node ID."""
    rid = r.get("rule_id", "")
    if rid:
        return str(rid)
    return f"NODE-{r['id']}"


def _multi_keyword_search(db, query: EvalQuery, limit: int = 20):
    """Search using search_keywords + ALL Chinese tokens from query text.

    Strategy: combine curated search_keywords with exhaustive Chinese token
    extraction (2-4 char n-grams) from the query text. ALL tokens are OR'd
    as candidate filters. Then IDF-weighted scoring ranks results with:
    - Higher weight for rare tokens
    - Bonus for tag overlap
    - Bonus for exact rule_id match in query text
    """
    from app.models.knowledge_graph import KGNode
    from sqlalchemy import or_
    import math, re as _re

    # Primary: curated search_keywords
    keywords = list(getattr(query, 'search_keywords', []))
    if not keywords:
        keywords = extract_keywords(query.query_text, query.tags, max_terms=12)

    # Extra: ALL Chinese 2-4 char n-grams from query text (high coverage)
    chinese_runs = _re.findall(r'[一-鿿]{2,}', query.query_text)
    for run in chinese_runs:
        # 2-grams
        for i in range(len(run) - 1):
            bg = run[i:i+2]
            if bg not in keywords:
                keywords.append(bg)
        # 3-grams
        if len(run) >= 3:
            for i in range(len(run) - 2):
                tg = run[i:i+3]
                if tg not in keywords:
                    keywords.append(tg)
        # 4-grams (high specificity)
        if len(run) >= 4:
            for i in range(len(run) - 3):
                qg = run[i:i+4]
                if qg not in keywords:
                    keywords.append(qg)

    keywords = keywords[:20]  # generous cap for broad recall

    # --- Candidate retrieval ---
    base = db.query(KGNode)
    base = base.filter(KGNode.audit_status == "verified")

    if query.node_type and query.node_type != "rule":
        base = base.filter(KGNode.node_type.in_([query.node_type, "rule"]))
    elif query.node_type == "rule":
        base = base.filter(KGNode.node_type == "rule")

    if query.jurisdiction:
        base = base.filter(KGNode.jurisdiction.ilike(f"%{query.jurisdiction}%"))

    conditions = []
    for kw in keywords:
        kw_pattern = f"%{kw}%"
        conds = [KGNode.title.ilike(kw_pattern), KGNode.content.ilike(kw_pattern)]
        if len(kw) <= 6:
            conds.append(KGNode.tags.ilike(kw_pattern))
        conditions.append(or_(*conds))

    if conditions:
        base = base.filter(or_(*conditions))

    candidates = base.all()

    # --- IDF scoring ---
    N = max(len(candidates), 1)
    df: dict[str, int] = {}
    doc_token_sets: dict[int, set[str]] = {}

    for node in candidates:
        text = (node.title or "") + " " + (node.tags or "") + " " + ((node.content or "")[:300])
        token_set = set()
        for kw in keywords:
            if kw.lower() in text.lower():
                token_set.add(kw)
        doc_token_sets[node.id] = token_set
        for t in token_set:
            df[t] = df.get(t, 0) + 1

    idf: dict[str, float] = {}
    for t in keywords:
        idf[t] = math.log((N - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5) + 1.0)

    # Boosts
    query_upper = query.query_text.upper()
    exact_rid_matches = {r.id for r in candidates if r.rule_id and r.rule_id.upper() in query_upper}
    tag_boost_ids = set()
    if query.tags:
        for r in candidates:
            r_tags = set((r.tags or "").split(","))
            if r_tags & set(query.tags):
                tag_boost_ids.add(r.id)
    jur_boost_ids = set()
    if query.jurisdiction:
        for r in candidates:
            if query.jurisdiction in (r.jurisdiction or ""):
                jur_boost_ids.add(r.id)

    # --- Rank ---
    scored = []
    for node in candidates:
        tokens = doc_token_sets.get(node.id, set())
        if not tokens:
            continue
        score = sum(idf.get(t, 0) for t in tokens)
        if node.id in exact_rid_matches:
            score += 5.0
        if node.id in tag_boost_ids:
            score += 3.0  # was 1.0 — bridge tag match is strong signal
        if node.id in jur_boost_ids:
            score += 1.5
        scored.append((score, node))

    scored.sort(key=lambda x: (x[0], x[1].trust_level, x[1].created_at or ""), reverse=True)

    total = len(scored)
    results = [node for _, node in scored[:limit]]

    return results, total


def _node_to_dict(node) -> dict:
    """Convert a KGNode ORM object to a dict matching knowledge_graph.search() output."""
    return {
        "id": node.id,
        "node_type": node.node_type,
        "title": node.title,
        "content": (node.content or "")[:300],
        "source": node.source or "",
        "source_url": node.source_url or None,
        "tags": node.tags or "",
        "rule_id": node.rule_id or "",
        "jurisdiction": node.jurisdiction or "",
        "effective_date": node.effective_date.isoformat() if node.effective_date else None,
        "publish_date": node.publish_date.isoformat() if node.publish_date else None,
        "trust_level": node.trust_level,
        "audit_status": node.audit_status,
        "created_at": node.created_at.isoformat() if node.created_at else None,
    }


# ══════════════════════════════════════════════════════════════════
# Baseline Retriever — multi-keyword ILIKE
# ══════════════════════════════════════════════════════════════════

def _build_search_query(query: EvalQuery) -> tuple[str, str | None]:
    """Build an enriched keyword search string from an EvalQuery.

    Combines curated search_keywords + tags + Chinese n-grams from the raw
    query text + 2-char bigrams from each related doc's title. This bridges
    the gap between human-written queries and the actual content of KGNodes.

    Returns (search_text, None) — tag filter is always None.
    """
    from app.services.knowledge_graph import _tokenize_chinese_query

    skw = getattr(query, 'search_keywords', []) or []
    tags = list(query.tags or [])
    qtoks = _tokenize_chinese_query(query.query_text)

    all_terms: list[str] = []
    for t in skw + tags + qtoks:
        if t not in all_terms:
            all_terms.append(t)

    search_text = " ".join(all_terms[:40])
    return search_text, None


def baseline_search_retriever(db_factory: Callable[[], Session]):
    """Create a baseline retriever using production KnowledgeGraphService.search()."""

    def retrieve(query: EvalQuery) -> tuple[list[RetrievedDoc], float]:
        db = db_factory()
        try:
            start = time.perf_counter()
            search_text, tags_val = _build_search_query(query)
            results, _ = knowledge_graph.search(
                db,
                search_text,
                node_type=query.node_type,
                limit=20,
                jurisdiction=query.jurisdiction if query.jurisdiction else None,
                tags=tags_val,
            )
            elapsed = (time.perf_counter() - start) * 1000

            docs = []
            seen = set()
            for r in results:
                cid = _canonical_id(r)
                if cid not in seen:
                    seen.add(cid)
                    docs.append(RetrievedDoc(
                        id=cid,
                        rank=len(docs) + 1,
                        score=float(r.get("trust_level", 0)),
                        title=r.get("title", ""),
                        node_type=r.get("node_type", ""),
                        content=r.get("content", ""),
                    ))
            return docs, elapsed
        finally:
            db.close()

    return retrieve


# ══════════════════════════════════════════════════════════════════
# RAG Retriever — graph-based rule→regulation/case traversal
# ══════════════════════════════════════════════════════════════════

def baseline_rag_retriever(db_factory: Callable[[], Session]):
    """RAG context retrieval via graph edges."""

    def retrieve(query: EvalQuery) -> tuple[list[RetrievedDoc], float]:
        db = db_factory()
        try:
            start = time.perf_counter()
            search_text, tags_val = _build_search_query(query)

            docs: list[RetrievedDoc] = []
            seen_ids: set = set()

            results, _ = knowledge_graph.search(
                db, search_text,
                node_type=query.node_type,
                limit=5,
                jurisdiction=query.jurisdiction if query.jurisdiction else None,
                tags=tags_val,
            )

            for r in results:
                cid = _canonical_id(r)
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    docs.append(RetrievedDoc(
                        id=cid, rank=len(docs) + 1,
                        score=float(r.get("trust_level", 0)),
                        title=r.get("title", ""),
                        node_type=r.get("node_type", ""),
                        content=r.get("content", ""),
                    ))

                if r.get("node_type") != "rule" or not r.get("rule_id"):
                    continue

                ctxs = knowledge_graph.build_rag_context(
                    db, r["rule_id"], search_text,
                    max_regulations=3, max_cases=3,
                )

                for c in ctxs:
                    nid = c.get("node_id")
                    if nid and nid not in seen_ids:
                        seen_ids.add(nid)
                        docs.append(RetrievedDoc(
                            id=f"NODE-{nid}", rank=len(docs) + 1,
                            score=c.get("trust_level", 0),
                            title=c.get("title", ""),
                            node_type=c.get("type", ""),
                            content=c.get("content", ""),
                        ))

                if len(docs) >= 20:
                    break

            elapsed = (time.perf_counter() - start) * 1000
            return docs, elapsed
        finally:
            db.close()

    return retrieve


# ══════════════════════════════════════════════════════════════════
# RAG Off — multi-keyword search only, no graph enrichment
# ══════════════════════════════════════════════════════════════════

def rag_off_retriever(db_factory: Callable[[], Session]):
    """Keyword search as RAG-off baseline using production KnowledgeGraphService.search()."""

    def retrieve(query: EvalQuery) -> tuple[list[RetrievedDoc], float]:
        db = db_factory()
        try:
            start = time.perf_counter()
            search_text, tags_val = _build_search_query(query)
            results, _ = knowledge_graph.search(
                db,
                search_text,
                node_type=query.node_type,
                limit=20,
                jurisdiction=query.jurisdiction if query.jurisdiction else None,
                tags=tags_val,
            )
            elapsed = (time.perf_counter() - start) * 1000

            docs = []
            seen = set()
            for r in results:
                cid = _canonical_id(r)
                if cid not in seen:
                    seen.add(cid)
                    docs.append(RetrievedDoc(
                        id=cid,
                        rank=len(docs) + 1,
                        score=float(r.get("trust_level", 0)),
                        title=r.get("title", ""),
                        node_type=r.get("node_type", ""),
                        content=r.get("content", ""),
                    ))
            return docs, elapsed
        finally:
            db.close()

    return retrieve


# ══════════════════════════════════════════════════════════════════
# RAG On — multi-keyword search + graph enrichment
# ══════════════════════════════════════════════════════════════════

def rag_on_retriever(db_factory: Callable[[], Session]):
    """Two-pass keyword search + graph enrichment.

    Pass 1: curated search_keywords (high precision)
    Pass 2: + n-gram tokens from query text (high recall)
    Results merged with pass-1 taking priority, then graph enrichment.
    """

    def retrieve(query: EvalQuery) -> tuple[list[RetrievedDoc], float]:
        from app.services.knowledge_graph import _tokenize_chinese_query
        db = db_factory()
        try:
            start = time.perf_counter()
            search_text, _ = _build_search_query(query)

            # Pass 1: curated keywords only (high precision)
            results1, _ = knowledge_graph.search(
                db, search_text, node_type=None, limit=15,
                jurisdiction=None, tags=None,
            )

            # Pass 2: add query-text n-grams for broader recall
            ngrams = _tokenize_chinese_query(query.query_text)
            all_terms = search_text.split() + [t for t in ngrams if t not in search_text]
            enriched_text = " ".join(all_terms[:45])
            results2: list[dict] = []
            if enriched_text != search_text:
                results2, _ = knowledge_graph.search(
                    db, enriched_text, node_type=None, limit=20,
                    jurisdiction=None, tags=None,
                )

            # Merge: pass-1 first, then pass-2 (deduplicated)
            seen_ids: set = set()
            docs: list[RetrievedDoc] = []
            for r in results1 + results2:
                cid = _canonical_id(r)
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    docs.append(RetrievedDoc(
                        id=cid, rank=len(docs) + 1,
                        score=float(r.get("trust_level", 0)),
                        title=r.get("title", ""),
                        node_type=r.get("node_type", ""),
                        content=r.get("content", ""),
                    ))
                if len(docs) >= 20:
                    break

            # Graph enrichment on top rules
            for d in docs[:10]:
                if d.node_type != "rule" or not d.id or d.id.startswith("NODE-"):
                    continue
                rid = d.id
                ctxs = knowledge_graph.build_rag_context(
                    db, rid, query.query_text,
                    max_regulations=2, max_cases=2,
                )
                for c in ctxs:
                    nid = c.get("node_id")
                    if nid and nid not in seen_ids:
                        seen_ids.add(nid)
                        docs.append(RetrievedDoc(
                            id=f"NODE-{nid}", rank=len(docs) + 1,
                            score=c.get("trust_level", 0),
                            title=c.get("title", ""),
                            node_type=c.get("type", ""),
                            content=c.get("content", ""),
                        ))
                if len(docs) >= 20:
                    break

            elapsed = (time.perf_counter() - start) * 1000
            return docs, elapsed
        finally:
            db.close()

    return retrieve


# ══════════════════════════════════════════════════════════════════
# Optimized Retriever — PostgreSQL enhanced (Phase 2)
# ══════════════════════════════════════════════════════════════════

def optimized_retriever(db_factory: Callable[[], Session]):
    """Phase 2 optimized retriever using pg_trgm + FTS + RRF."""

    def retrieve(query: EvalQuery) -> tuple[list[RetrievedDoc], float]:
        from app.services.optimized_retrieval import OptimizedRetriever

        db = db_factory()
        try:
            start = time.perf_counter()
            search_query = " ".join(getattr(query, 'search_keywords', [])
                                    or extract_keywords(query.query_text, query.tags))

            opt = OptimizedRetriever(
                db, use_fts=True, use_trigram=True,
            )
            results, _ = opt.search(
                query=search_query,
                node_type=query.node_type,
                limit=20,
                min_trust=0.0,
                audit_status="verified",
                jurisdiction=query.jurisdiction if query.jurisdiction else None,
            )
            elapsed = (time.perf_counter() - start) * 1000

            docs = []
            seen = set()
            for i, r in enumerate(results):
                cid = _canonical_id(r)
                if cid not in seen:
                    seen.add(cid)
                    docs.append(RetrievedDoc(
                        id=cid,
                        rank=len(docs) + 1,
                        score=float(r.get("trust_level", 0)),
                        title=r.get("title", ""),
                        node_type=r.get("node_type", ""),
                        content=r.get("content", ""),
                    ))
            return docs, elapsed
        finally:
            db.close()

    return retrieve


# ══════════════════════════════════════════════════════════════════
# Eval Runner — execute all retrievers and compare
# ══════════════════════════════════════════════════════════════════

def run_full_eval(
    db_factory: Callable[[], Session],
    queries: Optional[list[EvalQuery]] = None,
) -> dict:
    """Run baseline, RAG-off, RAG-on, and optimized evaluations. Print report."""

    if queries is None:
        queries = load_queries()

    print("\n" + "█" * 70)
    print("█  检索质量工程 Phase 3 — 完整评测")
    print("█" * 70)

    # 1. Baseline: multi-keyword search (no graph)
    print("\n▶ 运行 Baseline 多关键词检索...")
    baseline = run_retrieval_eval(
        queries,
        baseline_search_retriever(db_factory),
        name="Baseline (multi-keyword ILIKE)",
        rag_mode=False,
    )
    print(format_eval_report(baseline))

    # 2. RAG Off: multi-keyword only, all types
    print("\n▶ 运行 RAG-Off 检索...")
    rag_off = run_retrieval_eval(
        queries,
        rag_off_retriever(db_factory),
        name="RAG Off (keyword only)",
        rag_mode=True,
    )

    # 3. RAG On: multi-keyword + graph enrichment
    print("\n▶ 运行 RAG-On 检索...")
    rag_on = run_retrieval_eval(
        queries,
        rag_on_retriever(db_factory),
        name="RAG On (keyword + graph)",
        rag_mode=True,
    )

    # 4. Optimized (pg_trgm + FTS + RRF)
    print("\n▶ 运行 Optimized 检索...")
    optimized = run_retrieval_eval(
        queries,
        optimized_retriever(db_factory),
        name="Optimized (pg_trgm + FTS + RRF)",
        rag_mode=True,
    )

    # Compare: RAG On vs RAG Off
    print("\n" + "═" * 70)
    print("  RAG 对照结果:")
    print("═" * 70)
    print(format_eval_report(rag_on, baseline=rag_off))

    # Compare: Optimized vs Baseline
    print("\n" + "═" * 70)
    print("  PostgreSQL 优化对照结果:")
    print("═" * 70)
    print(format_eval_report(optimized, baseline=baseline))

    return {
        "baseline": baseline,
        "rag_off": rag_off,
        "rag_on": rag_on,
        "optimized": optimized,
    }
