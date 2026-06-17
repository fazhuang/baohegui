"""
Runtime seed 统计脚本 — 验证本轮质量修复
用法: cd backend && UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/verify_kg_seed.py
"""
import os
os.environ.setdefault("BHG_SECRET_KEY", "seed-verify-test-key-32chars-long!")
os.environ.setdefault("BHG_LLM_MOCK_MODE", "true")

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DB_URL = os.environ.get("BHG_DATABASE_URL", "sqlite:////private/tmp/bhg_kg_seed_verify.db")
engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if "sqlite" in DB_URL else {})

from app.core.audit import AuditBase
from app.models.announcement import Base as AnnouncementBase
from app.models.document import Base as DocumentBase
from app.models.knowledge_graph import KGNode, KGEdge
from app.models.rule import Base as RuleBase
from app.models.subscription import Base as SubscriptionBase
from app.models.complaint_case import Base as CCBase, ComplaintCase
from app.services.knowledge_graph import knowledge_graph
from datetime import date

for base in [DocumentBase, RuleBase, AuditBase, AnnouncementBase, SubscriptionBase, CCBase]:
    base.metadata.create_all(bind=engine, checkfirst=True)

SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

# 先清空旧数据
for t in ["kg_edges", "kg_nodes", "complaint_cases"]:
    db.execute(text(f"DELETE FROM {t}"))
db.commit()

# Seed
count = knowledge_graph.seed_builtin_knowledge(db)
print(f"Seed count: {count}")

# Stats
total = db.query(KGNode).count()
print(f"Total nodes: {total}")

by_type = {}
for nt in db.query(KGNode.node_type).distinct().all():
    cnt = db.query(KGNode).filter(KGNode.node_type == nt[0]).count()
    by_type[nt[0]] = cnt
    print(f"  {nt[0]}: {cnt}")
print(f"by_type: {by_type}")

by_status = {}
for st in db.query(KGNode.audit_status).distinct().all():
    cnt = db.query(KGNode).filter(KGNode.audit_status == st[0]).count()
    by_status[st[0]] = cnt
    print(f"  audit_status={st[0]}: {cnt}")
print(f"by_status: {by_status}")

total_edges = db.query(KGEdge).count()
print(f"Total edges: {total_edges}")

# Duplicate edge check
dup_edges = set()
dup_count = 0
for e in db.query(KGEdge).all():
    key = (e.source_id, e.target_id, e.relation)
    if key in dup_edges:
        dup_count += 1
        print(f"  DUPLICATE edge: src={e.source_id} tgt={e.target_id} rel={e.relation}")
    dup_edges.add(key)
print(f"Duplicate edge count: {dup_count}")

# CAT* in regulation check
cat_in_reg = db.query(KGNode).filter(
    KGNode.node_type == "regulation",
    KGNode.rule_id.like("CAT%")
).count()
print(f"CAT* in regulation: {cat_in_reg}")

# CAT* in concept
cat_in_concept = db.query(KGNode).filter(
    KGNode.node_type == "concept",
    KGNode.rule_id.like("CAT%")
).count()
print(f"CAT* in concept: {cat_in_concept}")

# R101/R107/R109 RAG context
for rid in ["R101", "R107", "R109"]:
    ctxs = knowledge_graph.build_rag_context(db, rid)
    non_empty = any(c.get("content") for c in ctxs) if ctxs else False
    print(f"RAG {rid}: {len(ctxs)} contexts, non_empty={non_empty}")

# ====== 手工 source_url 法规进入 RAG 时 source_url 不为空 ======
manual_reg = KGNode(
    node_type="regulation",
    title="手工法规-追溯测试",
    content="条款内容",
    source="国务院",
    source_url="https://law.example.gov/trace-test",
    effective_date=date(2025, 3, 1),
    publish_date=date(2025, 2, 15),
    jurisdiction="全国",
    trust_level=0.8,
    audit_status="verified",
)
db.add(manual_reg)
db.commit()
db.refresh(manual_reg)

manual_rule = KGNode(
    node_type="rule",
    title="R500: manual trace rule",
    content="测试",
    source="test",
    rule_id="R500",
    trust_level=0.8,
    audit_status="verified",
)
db.add(manual_rule)
db.commit()
db.refresh(manual_rule)

db.add(KGEdge(source_id=manual_rule.id, target_id=manual_reg.id, relation="references", weight=1.0))
db.commit()

ctxs = knowledge_graph.build_rag_context(db, "R500")
assert ctxs, "Should have RAG contexts"
ctx = ctxs[0]
print(f"source_url in RAG: '{ctx.get('source_url')}' (type={ctx.get('type')})")
assert ctx.get("source_url") == "https://law.example.gov/trace-test", \
    f"source_url leaked empty, got '{ctx.get('source_url')}'"
assert ctx.get("effective_date") == "2025-03-01"
assert ctx.get("publish_date") == "2025-02-15"
print("  ✓ source_url/effective_date/publish_date preserved")

# ====== 手工 rule->concept references 不进入 RAG ======
manual_concept = KGNode(
    node_type="concept",
    title="项目分类: 手工测试概念",
    content="概念",
    source="test",
    rule_id="CAT-MANUAL",
    trust_level=0.6,
    audit_status="verified",
)
db.add(manual_concept)
db.commit()
db.refresh(manual_concept)

db.add(KGEdge(source_id=manual_rule.id, target_id=manual_concept.id, relation="references", weight=1.0))
db.commit()

ctxs = knowledge_graph.build_rag_context(db, "R500")
concept_in_rag = any(c.get("node_id") == manual_concept.id for c in ctxs)
print(f"Concept in RAG via rule: {concept_in_rag} (should be False)")
assert not concept_in_rag, "Concept leaked into RAG!"

# ====== ComplaintCase 同步节点存在且 unreviewed，不进入 RAG ======
cc = ComplaintCase(
    province="甘肃",
    title="投诉案例-验证同步",
    project_name="测试项目",
    decision_type="upheld",
    complaint_types='["品牌锁定"]',
    legal_basis='["政府采购法"]',
    summary="测试摘要",
    is_analyzed=1,
)
db.add(cc)
db.commit()
db.refresh(cc)

knowledge_graph.seed_builtin_knowledge(db)

synced = db.query(KGNode).filter(
    KGNode.rule_id == f"CC-{cc.id}", KGNode.node_type == "case",
).first()
assert synced is not None, "ComplaintCase should be synced to KG"
print(f"ComplaintCase synced: id={synced.id}, audit_status={synced.audit_status}, trust={synced.trust_level}")
assert synced.audit_status == "unreviewed", f"Expected unreviewed, got {synced.audit_status}"
assert synced.trust_level == 0.55, f"Expected 0.55, got {synced.trust_level}"

# 验证不进入 RAG (find_similar_cases 需要 verified + trust >= 0.3)
similar = knowledge_graph.find_similar_cases(db, "品牌锁定", limit=20)
in_rag = any(s.get("id") == synced.id for s in similar)
print(f"Unreviewed case in RAG: {in_rag} (should be False)")
assert not in_rag, "Unreviewed case should not enter RAG!"
print("  ✓ ComplaintCase sync and RAG exclusion verified")

# Final dup check
final_edges = db.query(KGEdge).count()
dup_check = set()
final_dup = 0
for e in db.query(KGEdge).all():
    key = (e.source_id, e.target_id, e.relation)
    if key in dup_check:
        final_dup += 1
    dup_check.add(key)
print(f"Final duplicate edge count: {final_dup}")
assert final_dup == 0, f"Final duplicate edges: {final_dup}"

db.close()
print("\nALL CHECKS PASSED.")
