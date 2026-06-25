"""Phase 3 miss analysis: identify queries where Recall@5 < 1.0 and why.

Uses same setup as eval tests — seeds SQLite DB, runs the rag_on_retriever.
"""
import os, sys, json, time
import math as _math
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# --- Setup DB (matches test fixture) ---
DB_PATH = "./tests/eval_miss_analysis.db"
try:
    os.unlink(DB_PATH)
except OSError:
    pass

from app.models.knowledge_graph import Base as KGBase
from app.models.complaint_case import Base as CCBase
from app.models.document import Base as DocBase
from app.core.audit import AuditBase

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
KGBase.metadata.create_all(bind=engine)
CCBase.metadata.create_all(bind=engine)
DocBase.metadata.create_all(bind=engine)
AuditBase.metadata.create_all(bind=engine)
Session = sessionmaker(bind=engine)

# Seed
from app.services.knowledge_graph import knowledge_graph
with Session() as db:
    try:
        knowledge_graph.seed_builtin_knowledge(db)
    except Exception as e:
        db.rollback()
        print(f"Seed error: {e}")

# --- Run ---
from tests.eval.loader import load_queries
from tests.eval.retrievers import rag_on_retriever
from tests.eval.metrics import recall_at_k


def make_db_factory(Session):
    def factory():
        return Session()
    return factory


factory = make_db_factory(Session)
queries = load_queries()
retriever = rag_on_retriever(factory)

missed = []
empty_queries = []

# First pass: collect all query results for analysis
query_results = []
total_relevant_docs = 0
total_found_at_5 = 0
total_found_at_10 = 0

for q in queries:
    docs, latency = retriever(q)  # (list[RetrievedDoc], float)
    retrieved_ids = [d.id for d in docs]
    relevant_ids = [d.id for d in q.relevant_docs]
    rel_set = set(relevant_ids)

    r_at_5 = recall_at_k(retrieved_ids[:5], rel_set, 5)
    r_at_10 = recall_at_k(retrieved_ids[:10], rel_set, 10)

    total_relevant_docs += len(relevant_ids)
    total_found_at_5 += len(set(retrieved_ids[:5]) & rel_set)
    total_found_at_10 += len(set(retrieved_ids[:10]) & rel_set)

    if r_at_5 < 1.0:
        missed.append({
            "query_id": q.query_id,
            "query_text": q.query_text,
            "relevant_ids": relevant_ids,
            "top5_ids": retrieved_ids[:5],
            "top10_ids": retrieved_ids[:10],
            "r5": r_at_5,
            "r10": r_at_10,
            "top10_details": [
                {"id": d.id, "title": d.title, "score": d.score, "node_type": d.node_type}
                for d in docs[:10]
            ],
            "all_retrieved_count": len(docs),
        })
    if len(docs) == 0:
        empty_queries.append(q.query_id)

print(f"Total queries: {len(queries)}")
print(f"Total relevant docs (sum across queries): {total_relevant_docs}")
print(f"Found at top-5: {total_found_at_5}")
print(f"Found at top-10: {total_found_at_10}")
print(f"Overall Recall@5: {total_found_at_5/total_relevant_docs:.4f}")
print(f"Overall Recall@10: {total_found_at_10/total_relevant_docs:.4f}")
print(f"Missed Recall@5 queries: {len(missed)}")
print(f"Empty result queries: {len(empty_queries)}")
print()

# --- Categorize misses ---
reranker_fixable = 0   # relevant in top10 but not top5
need_better_recall = 0  # relevant not in top10 at all
partial_in_top5 = 0     # some but not all relevant in top5

for m in sorted(missed, key=lambda x: x["r5"]):
    rel_set = set(m["relevant_ids"])
    top5_set = set(m["top5_ids"])
    top10_set = set(m["top10_ids"])

    in_top10 = rel_set & (top10_set - top5_set)
    not_top10 = rel_set - top10_set
    in_top5 = rel_set & top5_set

    if not_top10:
        need_better_recall += 1
    if in_top10:
        reranker_fixable += 1
    if in_top5 and len(in_top5) < len(rel_set):
        partial_in_top5 += 1

    print(f"--- {m['query_id']}: {m['query_text'][:100]}")
    print(f"    Recall@5={m['r5']:.2f}, Recall@10={m['r10']:.2f}")
    print(f"    Expected: {m['relevant_ids']}")
    print(f"    Top5:     {m['top5_ids']}")
    if not_top10:
        print(f"    *** NOT in top10: {not_top10} (NEEDS BETTER RECALL)")
    if in_top10:
        print(f"    *** In top10 NOT top5: {in_top10} (RERANKER WOULD FIX)")
        for item in m["top10_details"]:
            if item["id"] in in_top10:
                print(f"        -> {item['id']} (score={item['score']:.4f}) title={item['title'][:80]}")
    print()

print("=" * 70)
print("SUMMARY BY FAILURE MODE")
print("=" * 70)
print(f"RERANKER-FIXABLE (in top10, not top5): {reranker_fixable}")
print(f"NEED BETTER RECALL (not in top10):    {need_better_recall}")
print(f"PARTIAL IN TOP5:                      {partial_in_top5}")
print(f"TOTAL MISSED:                        {len(missed)}")

# Estimate: if we fix ranking alone (push top10-relevant into top5):
# New Recall@5 ~= total_found_at_10 / total_relevant_docs (assuming all top10-relevant move to top5)
# But that's an upper bound — what's realistic is finding the overlap case
# Actually: reranker can move relevant-from-top10 into top5, improving recall@5
# The improvement = sum of (relevant docs moved from top10 to top5) / total_relevant
# For each query, if all relevant docs are already in top10, a perfect reranker would give Recall@5 = Recall@10
# So the maximum improvement from reranking alone is Recall@10 - Recall@5 = 0.9012 - 0.6020 = ~0.30
print(f"\nMax reranker-only improvement: Recall@10 - Recall@5 = {total_found_at_10/total_relevant_docs:.4f} - {total_found_at_5/total_relevant_docs:.4f} = {(total_found_at_10 - total_found_at_5)/total_relevant_docs:.4f}")
print(f"Reranker ceiling (if all top10-relevant → top5): {total_found_at_10/total_relevant_docs:.4f}")

# Cleanup
try:
    os.unlink(DB_PATH)
except OSError:
    pass
