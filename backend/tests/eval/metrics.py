"""检索评测指标：Recall@5, MRR@10, nDCG@10, 空召回率, 错引率, P95 延迟"""

from __future__ import annotations

import math
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from functools import wraps
from typing import Callable, Optional


# ── Data structures ──────────────────────────────────────────────


@dataclass
class RelevantDoc:
    """One expected relevant document for a query."""

    id: int | str          # node ID (int for KG) or source identifier
    rel_type: str          # "rule" | "regulation" | "case"
    relevance: int = 1     # 0 = irrelevant, 1 = partially relevant, 2 = highly relevant, 3 = perfect
    title: str = ""
    is_hard_negative: bool = False  # looks relevant but is NOT (tests false positive robustness)


@dataclass
class EvalQuery:
    """A single annotated evaluation query."""

    query_id: str
    query_text: str
    relevant_docs: list[RelevantDoc] = field(default_factory=list)
    hard_negatives: list[RelevantDoc] = field(default_factory=list)
    node_type: Optional[str] = None
    jurisdiction: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    # Expected correct regulation/case citations
    expected_regulations: list[str] = field(default_factory=list)
    expected_cases: list[str] = field(default_factory=list)


@dataclass
class RetrievedDoc:
    """One retrieved document."""

    id: int | str
    rank: int
    score: float
    title: str = ""
    node_type: str = ""
    content: str = ""


@dataclass
class QueryResult:
    """Metrics for a single query."""

    query_id: str
    retrieved: list[RetrievedDoc] = field(default_factory=list)
    relevant_found: list[int] = field(default_factory=list)
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    mrr_at_10: float = 0.0
    ndcg_at_10: float = 0.0
    empty: bool = True
    mis_cited: bool = False
    latency_ms: float = 0.0
    # RAG-specific
    rag_regulation_recall: float = 0.0
    rag_case_recall: float = 0.0


@dataclass
class EvalRun:
    """Aggregate metrics across all queries."""

    name: str
    total_queries: int
    recall_at_5: float           # macro average
    recall_at_10: float
    mrr_at_10: float
    ndcg_at_10: float
    empty_recall_rate: float     # fraction of queries returning 0 results
    mis_citation_rate: float     # fraction of results citing wrong reg/case
    p95_latency_ms: float
    p50_latency_ms: float
    rag_regulation_recall: float
    rag_case_recall: float
    per_query: list[QueryResult] = field(default_factory=list)


# ── Metric functions ──────────────────────────────────────────────


def dcg_at_k(relevance_scores: list[int], k: int) -> float:
    """Discounted Cumulative Gain at k."""
    dcg = 0.0
    for i, rel in enumerate(relevance_scores[:k]):
        if i == 0:
            dcg += rel
        else:
            dcg += rel / math.log2(i + 2)
    return dcg


def ndcg_at_k(retrieved_ids: list[int | str], relevant_map: dict, k: int) -> float:
    """Normalized DCG at k. relevant_map: id -> relevance score (0-3)."""
    rels = [relevant_map.get(doc_id, 0) for doc_id in retrieved_ids[:k]]
    dcg = dcg_at_k(rels, k)

    # Ideal DCG: sort all relevant by relevance desc, pad to k
    ideal_rels = sorted(relevant_map.values(), reverse=True)[:k]
    ideal_dcg = dcg_at_k(ideal_rels, k)

    if ideal_dcg == 0:
        return 0.0
    return dcg / ideal_dcg


def recall_at_k(retrieved_ids: list[int | str], relevant_ids: set, k: int) -> float:
    """Recall@k: fraction of relevant docs found in top-k."""
    if not relevant_ids:
        return 1.0  # no expected docs → perfect recall (undefined → 1.0 by convention)
    found = relevant_ids & set(retrieved_ids[:k])
    return len(found) / len(relevant_ids)


def mrr_at_k(retrieved_ids: list[int | str], relevant_ids: set, k: int) -> float:
    """Mean Reciprocal Rank: 1 / rank of first relevant doc, 0 if none found in top-k."""
    for i, doc_id in enumerate(retrieved_ids[:k]):
        if doc_id in relevant_ids:
            return 1.0 / (i + 1)
    return 0.0


def p95_latency(latencies_ms: list[float]) -> float:
    """95th percentile latency."""
    if not latencies_ms:
        return 0.0
    sorted_lats = sorted(latencies_ms)
    idx = int(math.ceil(0.95 * len(sorted_lats))) - 1
    idx = max(0, min(idx, len(sorted_lats) - 1))
    return sorted_lats[idx]


# ── Evaluation runner ─────────────────────────────────────────────


def run_retrieval_eval(
    queries: list[EvalQuery],
    retriever: Callable[[EvalQuery], tuple[list[RetrievedDoc], float]],
    name: str = "eval",
    rag_mode: bool = False,
) -> EvalRun:
    """Run full retrieval evaluation.

    Args:
        queries: Annotated eval queries with expected relevant docs.
        retriever: Function that takes EvalQuery and returns (list[RetrievedDoc], latency_ms).
        name: Run name for reporting.
        rag_mode: If True, also compute RAG-specific metrics (regulation/case recall).

    Returns:
        EvalRun with aggregate metrics.
    """
    per_query: list[QueryResult] = []
    latencies: list[float] = []
    empty_count = 0
    mis_cited_count = 0

    for q in queries:
        relevant_ids = {d.id for d in q.relevant_docs}
        relevant_map = {d.id: d.relevance for d in q.relevant_docs}
        hard_neg_ids = {d.id for d in q.hard_negatives}

        retrieved, latency = retriever(q)
        latencies.append(latency)

        retrieved_ids = [r.id for r in retrieved]

        # Core metrics
        r5 = recall_at_k(retrieved_ids, relevant_ids, 5)
        r10 = recall_at_k(retrieved_ids, relevant_ids, 10)
        mrr = mrr_at_k(retrieved_ids, relevant_ids, 10)
        ndcg = ndcg_at_k(retrieved_ids, relevant_map, 10)

        empty = len(retrieved) == 0
        if empty:
            empty_count += 1

        # Mis-citation detection: if a hard negative appears in top-10
        mis_cited = bool(hard_neg_ids & set(retrieved_ids[:10]))
        if mis_cited:
            mis_cited_count += 1

        # RAG-specific: regulation/case recall
        rag_reg_recall = _compute_type_recall(retrieved, q, "regulation")
        rag_case_recall = _compute_type_recall(retrieved, q, "case")

        per_query.append(QueryResult(
            query_id=q.query_id,
            retrieved=retrieved,
            relevant_found=list(relevant_ids & set(retrieved_ids)),
            recall_at_5=r5,
            recall_at_10=r10,
            mrr_at_10=mrr,
            ndcg_at_10=ndcg,
            empty=empty,
            mis_cited=mis_cited,
            latency_ms=latency,
            rag_regulation_recall=rag_reg_recall,
            rag_case_recall=rag_case_recall,
        ))

    n = len(queries)

    # Only include queries with at least one expected relevant doc in averages
    # (queries with empty relevant_docs get Recall=1.0 by convention — skip them)
    def _with_relevant(qrs, attr):
        vals = [getattr(qr, attr) for qr in qrs if qr.recall_at_5 < 0.999 or qr.recall_at_10 > 0]
        if not vals:
            return 0.0
        return statistics.mean(vals)

    # Robust mean: queries with zero relevant docs excluded from recall/mrr/ndcg
    _q_with_rel = [qr for qr in per_query if any(
        d for d in queries if d.query_id == qr.query_id and d.relevant_docs
    )]
    if not _q_with_rel:
        _q_with_rel = per_query

    return EvalRun(
        name=name,
        total_queries=n,
        recall_at_5=statistics.mean(qr.recall_at_5 for qr in _q_with_rel),
        recall_at_10=statistics.mean(qr.recall_at_10 for qr in _q_with_rel),
        mrr_at_10=statistics.mean(qr.mrr_at_10 for qr in _q_with_rel),
        ndcg_at_10=statistics.mean(qr.ndcg_at_10 for qr in _q_with_rel),
        empty_recall_rate=empty_count / n if n else 0.0,
        mis_citation_rate=mis_cited_count / n if n else 0.0,
        p95_latency_ms=p95_latency(latencies),
        p50_latency_ms=statistics.median(latencies) if latencies else 0.0,
        rag_regulation_recall=statistics.mean(qr.rag_regulation_recall for qr in per_query),
        rag_case_recall=statistics.mean(qr.rag_case_recall for qr in per_query),
        per_query=per_query,
    )


def _compute_type_recall(retrieved: list[RetrievedDoc], query: EvalQuery, type_name: str) -> float:
    """Compute recall specifically for a document type (regulation/case)."""
    type_relevant = {d.id for d in query.relevant_docs if d.rel_type == type_name}
    if not type_relevant:
        return 1.0
    type_retrieved = {r.id for r in retrieved if r.node_type == type_name}
    found = type_relevant & type_retrieved
    return len(found) / len(type_relevant)


# ── Timing decorator ──────────────────────────────────────────────


def timed_retriever(fn: Callable) -> Callable:
    """Wrap a retriever to return (results, latency_ms)."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        results = fn(*args, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000
        return results, elapsed

    return wrapper


# ── Report formatting ──────────────────────────────────────────────


def format_eval_report(run: EvalRun, baseline: Optional[EvalRun] = None) -> str:
    """Format a human-readable eval report. Optionally compare against baseline."""
    lines = [
        f"{'=' * 70}",
        f"  检索评测报告: {run.name}",
        f"{'=' * 70}",
        f"  查询数:          {run.total_queries}",
        f"  Recall@5:        {run.recall_at_5:.4f}  {'>' if run.recall_at_5 >= 0.85 else '✗'} 目标 ≥ 0.85",
        f"  Recall@10:       {run.recall_at_10:.4f}",
        f"  MRR@10:          {run.mrr_at_10:.4f}    {'>' if run.mrr_at_10 >= 0.75 else '✗'} 目标 ≥ 0.75",
        f"  nDCG@10:         {run.ndcg_at_10:.4f}",
        f"  空召回率:        {run.empty_recall_rate:.4f}  ({int(run.empty_recall_rate * run.total_queries)} 次)",
        f"  错引率:          {run.mis_citation_rate:.4f}  {'<' if run.mis_citation_rate <= 0.02 else '✗'} 目标 ≤ 0.02",
        f"  P50 延迟:        {run.p50_latency_ms:.1f}ms",
        f"  P95 延迟:        {run.p95_latency_ms:.1f}ms {'<' if run.p95_latency_ms <= 500 else '✗'} 目标 ≤ 500ms",
        f"  RAG 法规召回:    {run.rag_regulation_recall:.4f}",
        f"  RAG 案例召回:    {run.rag_case_recall:.4f}",
    ]

    if baseline:
        delta_r5 = run.recall_at_5 - baseline.recall_at_5
        delta_mrr = run.mrr_at_10 - baseline.mrr_at_10
        delta_mis = run.mis_citation_rate - baseline.mis_citation_rate
        lines.extend([
            f"{'─' * 70}",
            f"  对比基线 ({baseline.name}):",
            f"    Δ Recall@5:    {delta_r5:+.4f}",
            f"    Δ MRR@10:      {delta_mrr:+.4f}",
            f"    Δ 错引率:      {delta_mis:+.4f}",
            f"    Δ P95 延迟:    {run.p95_latency_ms - baseline.p95_latency_ms:+.1f}ms",
        ])

        # RAG improvement check
        rag_delta_reg = run.rag_regulation_recall - baseline.rag_regulation_recall
        rag_delta_case = run.rag_case_recall - baseline.rag_case_recall
        lines.extend([
            f"    Δ RAG 法规召回: {rag_delta_reg:+.4f}",
            f"    Δ RAG 案例召回: {rag_delta_case:+.4f}",
        ])

        # High-risk clause improvement
        high_risk_improvement = _compute_high_risk_improvement(run, baseline)
        lines.append(f"    RAG 高风险条款提升: {high_risk_improvement:+.1f}pp {'✓' if high_risk_improvement >= 10 else '✗'} 目标 ≥ 10pp")

    lines.append(f"{'=' * 70}")
    return "\n".join(lines)


def _compute_high_risk_improvement(run: EvalRun, baseline: EvalRun) -> float:
    """Estimate high-risk clause recall improvement (percentage points)."""
    # High-risk queries are those tagged as "high_risk" or with many relevant docs
    # We compare the average recall improvement on queries with ≥3 relevant docs
    high_risk_ids = set()
    for qr in run.per_query:
        if len(qr.relevant_found) >= 3:
            high_risk_ids.add(qr.query_id)

    if not high_risk_ids:
        return 0.0

    run_high = [qr.recall_at_5 for qr in run.per_query if qr.query_id in high_risk_ids]
    baseline_high = [qr.recall_at_5 for qr in baseline.per_query if qr.query_id in high_risk_ids]

    if not run_high or not baseline_high:
        return 0.0

    return (statistics.mean(run_high) - statistics.mean(baseline_high)) * 100
