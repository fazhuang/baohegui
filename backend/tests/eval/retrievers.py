"""Phase 3 检索评估套件 — 连接评测框架与知识图谱服务

所有检索器仅使用生产 KnowledgeGraphService.search() 的真实调用链。
输入只能来自 query_text 及真实 API 可提供的参数（tags, node_type, jurisdiction）。

禁止将 search_keywords、相关文档标题、expected_* 或 hard_negatives 注入查询。

检索器返回的 RetrievedDoc.id 统一为 canonical ID 字符串：
- rule 节点：rule_id（如 "R001"）
- 非 rule 节点：f"NODE-{id}"（如 "NODE-433"）

Canonical ID 格式：
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.services.knowledge_graph import knowledge_graph
from app.services.query_expansion import expand_query
from .metrics import EvalQuery, RetrievedDoc, EvalRun, run_retrieval_eval, format_eval_report
from .loader import load_queries


def _canonical_id(r: dict) -> str:
    """Return string canonical ID: rule_id preferred, else node ID."""
    rid = r.get("rule_id", "")
    if rid:
        return str(rid)
    return f"NODE-{r['id']}"


# ══════════════════════════════════════════════════════════════════
# 生产路径查询构造 — 仅从 query_text + tags 派生搜索词
# ══════════════════════════════════════════════════════════════════

def _build_search_text(query: EvalQuery) -> str:
    """从 query_text + tags 构造搜索字符串（仅使用生产路径可得的输入）。

    使用 query_expansion 服务（生产级）进行领域词典匹配和同义词扩展。
    扩展结果仅由用户原始查询 + tags 确定，不依赖 search_keywords 或标注。
    """
    return expand_query(query.query_text, query.tags, max_terms=40)


def _search_with_production_path(
    db, query: EvalQuery, limit: int = 20
) -> tuple[list[dict], int]:
    """Call knowledge_graph.search() with production input only.

    Args:
        db: SQLAlchemy session
        query: EvalQuery with query_text, tags, node_type, jurisdiction
        limit: Max results

    Returns:
        (results, total) from knowledge_graph.search()
    """
    search_text = _build_search_text(query)

    results, total = knowledge_graph.search(
        db,
        search_text,
        node_type=query.node_type,
        limit=limit,
        jurisdiction=query.jurisdiction if query.jurisdiction else None,
        tags=None,  # tags mixed into search_text for tokenization
    )
    return results, total


def _results_to_docs(results: list[dict]) -> list[RetrievedDoc]:
    """Convert knowledge_graph.search() results to RetrievedDoc list."""
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
    return docs


# ══════════════════════════════════════════════════════════════════
# Baseline Retriever — production KnowledgeGraphService.search()
# ══════════════════════════════════════════════════════════════════

def baseline_search_retriever(db_factory: Callable[[], Session]):
    """Create a baseline retriever using production KnowledgeGraphService.search()."""

    def retrieve(query: EvalQuery) -> tuple[list[RetrievedDoc], float]:
        db = db_factory()
        try:
            start = time.perf_counter()
            results, _ = _search_with_production_path(db, query, limit=20)
            docs = _results_to_docs(results)
            elapsed = (time.perf_counter() - start) * 1000
            return docs, elapsed
        finally:
            db.close()

    return retrieve


# ══════════════════════════════════════════════════════════════════
# RAG Off — keyword search only, no graph enrichment
# ══════════════════════════════════════════════════════════════════

def rag_off_retriever(db_factory: Callable[[], Session]):
    """Keyword search as RAG-off baseline — production KnowledgeGraphService.search()."""

    def retrieve(query: EvalQuery) -> tuple[list[RetrievedDoc], float]:
        db = db_factory()
        try:
            start = time.perf_counter()
            results, _ = _search_with_production_path(db, query, limit=20)
            docs = _results_to_docs(results)
            elapsed = (time.perf_counter() - start) * 1000
            return docs, elapsed
        finally:
            db.close()

    return retrieve


# ══════════════════════════════════════════════════════════════════
# RAG Retriever (graph-enhanced) — experimental path
# ══════════════════════════════════════════════════════════════════

def baseline_rag_retriever(db_factory: Callable[[], Session]):
    """RAG context retrieval — keyword search + graph edge traversal.

    实验路径：base search → graph enrichment → merge before truncation.
    """

    def retrieve(query: EvalQuery) -> tuple[list[RetrievedDoc], float]:
        db = db_factory()
        try:
            start = time.perf_counter()
            results, _ = _search_with_production_path(db, query, limit=10)

            docs: list[RetrievedDoc] = []
            seen_ids: set = set()

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

                # Graph enrichment: follow edges for rules with rule_id
                if r.get("node_type") != "rule" or not r.get("rule_id"):
                    continue

                ctxs = knowledge_graph.build_rag_context(
                    db, r["rule_id"], query.query_text,
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
# RAG On — keyword search + graph enrichment, merged before truncation
# ══════════════════════════════════════════════════════════════════

def rag_on_retriever(db_factory: Callable[[], Session]):
    """Keyword search + graph enrichment — merged before Top-K truncation.

    实验路径：
    1. Base search via production KnowledgeGraphService.search()
    2. Graph enrichment on top rules
    3. Enriched docs inserted alongside base docs (title-based dedup)
    4. Final top-20 truncation after merge
    """

    def retrieve(query: EvalQuery) -> tuple[list[RetrievedDoc], float]:
        db = db_factory()
        try:
            start = time.perf_counter()
            results, _ = _search_with_production_path(db, query, limit=15)

            seen_titles: set[str] = set()
            base_docs: list[RetrievedDoc] = []
            enriched_docs: list[RetrievedDoc] = []

            for r in results:
                cid = _canonical_id(r)
                if cid not in seen_titles:
                    seen_titles.add(cid)
                    title = r.get("title", "")
                    base_docs.append(RetrievedDoc(
                        id=cid, rank=0,  # rank assigned after merge
                        score=float(r.get("trust_level", 0)),
                        title=title,
                        node_type=r.get("node_type", ""),
                        content=r.get("content", ""),
                    ))

            # Graph enrichment: follow edges for top rules (by rank order)
            enriched_ids: set = set()
            for d in base_docs[:10]:
                if d.node_type != "rule" or not d.id or d.id.startswith("NODE-"):
                    continue
                # Resolve rule_id from the doc ID (which IS the rule_id for rules)
                rid = d.id
                ctxs = knowledge_graph.build_rag_context(
                    db, rid, query.query_text,
                    max_regulations=2, max_cases=2,
                )
                for c in ctxs:
                    nid = c.get("node_id")
                    if nid and nid not in enriched_ids:
                        enriched_ids.add(nid)
                        title = c.get("title", "")
                        cid = f"NODE-{nid}"
                        if cid not in seen_titles:
                            seen_titles.add(cid)
                            enriched_docs.append(RetrievedDoc(
                                id=cid, rank=0,
                                score=c.get("trust_level", 0),
                                title=title,
                                node_type=c.get("type", ""),
                                content=c.get("content", ""),
                            ))

            # Merge: interleave enriched docs after every ~3 base results
            merged: list[RetrievedDoc] = []
            enriched_iter = iter(enriched_docs)
            for i, d in enumerate(base_docs):
                merged.append(d)
                # Insert enrichment every 3 base docs
                if (i + 1) % 3 == 0:
                    try:
                        merged.append(next(enriched_iter))
                    except StopIteration:
                        pass
            # Append any remaining enriched docs
            merged.extend(enriched_iter)

            # Assign final ranks
            for rank, d in enumerate(merged[:20], 1):
                d.rank = rank

            elapsed = (time.perf_counter() - start) * 1000
            return merged[:20], elapsed
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
    """Run baseline, RAG-off, and RAG-on evaluations. Print report."""

    if queries is None:
        queries = load_queries()

    print("\n" + "█" * 70)
    print("█  检索质量工程 Phase 3 — 完整评测（生产路径）")
    print("█" * 70)

    # 1. Baseline: production KnowledgeGraphService.search()
    print("\n▶ 运行 Baseline 生产路径检索...")
    baseline = run_retrieval_eval(
        queries,
        baseline_search_retriever(db_factory),
        name="Baseline (生产路径 KG.search)",
        rag_mode=False,
    )
    print(format_eval_report(baseline))

    # 2. RAG Off: identical to baseline (same production path, no enrichment)
    print("\n▶ 运行 RAG-Off 检索（同基线，无图谱增强）...")
    rag_off = run_retrieval_eval(
        queries,
        rag_off_retriever(db_factory),
        name="RAG Off (无图谱增强)",
        rag_mode=True,
    )

    # 3. RAG On: experimental — keyword search + graph enrichment
    print("\n▶ 运行 RAG-On 检索（实验：关键词+图谱增强）...")
    rag_on = run_retrieval_eval(
        queries,
        rag_on_retriever(db_factory),
        name="RAG On (实验: 关键词+图谱)",
        rag_mode=True,
    )

    # Compare: RAG On vs RAG Off
    print("\n" + "═" * 70)
    print("  RAG 对照结果 (RAG On vs RAG Off):")
    print("═" * 70)
    print(format_eval_report(rag_on, baseline=rag_off))

    return {
        "baseline": baseline,
        "rag_off": rag_off,
        "rag_on": rag_on,
    }
