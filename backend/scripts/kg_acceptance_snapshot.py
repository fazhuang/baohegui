#!/usr/bin/env python3
"""
KG 验收快照脚本 — 只读 + 临时数据自动清理，输出 JSON 供 Codex 复验

用法（推荐在临时 SQLite 库上先 seed 后跑）：
  cd backend
  rm -f /private/tmp/bhg_kg_snap.db
  BHG_DATABASE_URL=sqlite:////private/tmp/bhg_kg_snap.db \
    UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/kg_acceptance_snapshot.py

如果库为空会提示先 seed。
trace_checks 中的 references_to_concept_api_rejected 标记为 not_checked
（由 pytest test_admin_cannot_create_references_to_concept 覆盖）。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone

# ── 环境必须在导入 app 之前 ──────────────────────────
os.environ.setdefault("BHG_SECRET_KEY", "kg-acceptance-snapshot-key-32ch-min!")
os.environ.setdefault("BHG_LLM_MOCK_MODE", "true")
os.environ.setdefault("BHG_DEBUG", "true")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DB_URL = os.environ.get("BHG_DATABASE_URL", "sqlite:////private/tmp/bhg_kg_snap.db")
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DB_URL else {},
)

# 确保所有表存在
from app.core.audit import AuditBase
from app.models.announcement import Base as AnnouncementBase
from app.models.complaint_case import Base as CCBase, ComplaintCase
from app.models.document import Base as DocumentBase
from app.models.knowledge_graph import KGNode, KGEdge
from app.models.rule import Base as RuleBase
from app.models.subscription import Base as SubscriptionBase

for base in [DocumentBase, RuleBase, AuditBase, AnnouncementBase, SubscriptionBase, CCBase]:
    base.metadata.create_all(bind=engine, checkfirst=True)

SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

from app.services.knowledge_graph import knowledge_graph

EXIT_CODE = 0


def fail(msg: str) -> None:
    global EXIT_CODE
    print(f"FAIL: {msg}", file=sys.stderr)
    EXIT_CODE = 1


# ═══════════════════════════════════════════════════════════════
# 0. 检查是否已 seed
# ═══════════════════════════════════════════════════════════════
node_count = db.query(KGNode).count()
if node_count == 0:
    print("INFO: 数据库无 KG 节点，先执行 seed...")
    knowledge_graph.seed_builtin_knowledge(db)
    node_count = db.query(KGNode).count()
    if node_count == 0:
        fail("Seed 后仍无节点，请检查 rules/ 目录是否存在")
        db.close()
        sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# 1. 基础统计
# ═══════════════════════════════════════════════════════════════
total_nodes = db.query(KGNode).count()
total_edges = db.query(KGEdge).count()

by_type: dict[str, int] = {}
for nt in db.query(KGNode.node_type).distinct().all():
    by_type[nt[0]] = db.query(KGNode).filter(KGNode.node_type == nt[0]).count()

by_status: dict[str, int] = {}
for st in db.query(KGNode.audit_status).distinct().all():
    by_status[st[0]] = db.query(KGNode).filter(KGNode.audit_status == st[0]).count()

# 重复边
dup_keys = set()
dup_count = 0
for e in db.query(KGEdge).all():
    key = (e.source_id, e.target_id, e.relation)
    if key in dup_keys:
        dup_count += 1
    dup_keys.add(key)

# CAT* 分类节点分布
cat_in_regulation = db.query(KGNode).filter(
    KGNode.node_type == "regulation", KGNode.rule_id.like("CAT%")
).count()
cat_concept = db.query(KGNode).filter(
    KGNode.node_type == "concept", KGNode.rule_id.like("CAT%")
).count()

# ComplaintCase 同步
complaint_case_total = db.query(ComplaintCase).count()
complaint_case_nodes = db.query(KGNode).filter(
    KGNode.node_type == "case", KGNode.rule_id.like("CC-%")
).count()
unreviewed_cc_nodes = db.query(KGNode).filter(
    KGNode.node_type == "case",
    KGNode.rule_id.like("CC-%"),
    KGNode.audit_status == "unreviewed",
).count()

# 规则覆盖率
rules_total = db.query(KGNode).filter(KGNode.node_type == "rule").count()
rules_with_out_edge = 0
for r in db.query(KGNode).filter(KGNode.node_type == "rule").all():
    edge_exists = db.query(KGEdge).filter(KGEdge.source_id == r.id).first()
    if edge_exists:
        rules_with_out_edge += 1
rule_coverage_ratio = round(rules_with_out_edge / rules_total, 4) if rules_total > 0 else 0.0

# ═══════════════════════════════════════════════════════════════
# 2. RAG 采样
# ═══════════════════════════════════════════════════════════════
rag_samples: dict[str, dict] = {}
for rid in ["R101", "R107", "R109"]:
    ctxs = knowledge_graph.build_rag_context(db, rid)
    rag_samples[rid] = {
        "context_count": len(ctxs),
        "types": [c.get("type") for c in ctxs],
        "node_ids": [c.get("node_id") for c in ctxs],
        "trust_levels": [c.get("trust_level") for c in ctxs],
    }

# ═══════════════════════════════════════════════════════════════
# 3. 可追溯性检查（临时数据，自动清理）
# ═══════════════════════════════════════════════════════════════
trace_checks: dict[str, dict] = {}
tmp_src_id: int | None = None
tmp_tgt_id: int | None = None
tmp_concept_id: int | None = None
tmp_cc_id: int | None = None

try:
    # 3a. source_url 保留验证
    tmp_reg = KGNode(
        node_type="regulation",
        title="[ACCEPTANCE-TMP-R001] source_url trace test",
        content="测试条款",
        source="财政部",
        source_url="https://law.example.gov/acceptance-test",
        effective_date=date(2025, 6, 1),
        publish_date=date(2025, 5, 20),
        jurisdiction="全国",
        trust_level=0.8,
        audit_status="verified",
    )
    db.add(tmp_reg)
    db.flush()
    tmp_tgt_id = tmp_reg.id

    tmp_rule = KGNode(
        node_type="rule",
        title="ACCEPTANCE-TMP-R001: trace rule",
        content="测试",
        source="test",
        rule_id="ACCEPTANCE-TMP-R001",
        trust_level=0.8,
        audit_status="verified",
    )
    db.add(tmp_rule)
    db.flush()
    tmp_src_id = tmp_rule.id

    db.add(KGEdge(source_id=tmp_rule.id, target_id=tmp_reg.id, relation="references", weight=1.0))
    db.flush()

    ctxs = knowledge_graph.build_rag_context(db, "ACCEPTANCE-TMP-R001")
    if ctxs:
        ctx = ctxs[0]
        trace_checks["source_url_preserved"] = {
            "passed": ctx.get("source_url") == "https://law.example.gov/acceptance-test",
            "expected": "https://law.example.gov/acceptance-test",
            "actual": ctx.get("source_url"),
            "effective_date": ctx.get("effective_date"),
            "publish_date": ctx.get("publish_date"),
        }
        if not trace_checks["source_url_preserved"]["passed"]:
            fail(f"source_url 未保留: expected https://..., got '{ctx.get('source_url')}'")
    else:
        trace_checks["source_url_preserved"] = {"passed": False, "error": "No RAG contexts returned"}
        fail("source_url_preserved: RAG 返回空")

    # 3b. concept 不进入 RAG
    tmp_concept = KGNode(
        node_type="concept",
        title="[ACCEPTANCE-TMP-CONCEPT] concept exclusion test",
        content="概念内容",
        source="test",
        rule_id="ACCEPTANCE-TMP-C001",
        trust_level=0.6,
        audit_status="verified",
    )
    db.add(tmp_concept)
    db.flush()
    tmp_concept_id = tmp_concept.id

    db.add(KGEdge(source_id=tmp_rule.id, target_id=tmp_concept.id, relation="references", weight=1.0))
    db.flush()

    ctxs = knowledge_graph.build_rag_context(db, "ACCEPTANCE-TMP-R001")
    leaked = any(c.get("node_id") == tmp_concept.id for c in ctxs)
    trace_checks["concept_excluded_from_rag"] = {
        "passed": not leaked,
        "concept_id": tmp_concept.id,
        "leaked": leaked,
    }
    if leaked:
        fail("concept 进入了 RAG 法规依据")

    # 3c. ComplaintCase 同步 + 不进 RAG
    cc = ComplaintCase(
        province="甘肃",
        title="[ACCEPTANCE-TMP-CC] 投诉案例-验收同步",
        project_name="验收测试项目",
        decision_type="upheld",
        complaint_types='["品牌锁定"]',
        legal_basis='["政府采购法"]',
        summary="验收测试摘要",
        is_analyzed=1,
    )
    db.add(cc)
    db.flush()
    tmp_cc_id = cc.id

    # 幂等 seed
    knowledge_graph.seed_builtin_knowledge(db)

    synced = db.query(KGNode).filter(
        KGNode.rule_id == f"CC-{cc.id}", KGNode.node_type == "case"
    ).first()
    if synced:
        similar = knowledge_graph.find_similar_cases(db, "品牌锁定", limit=20)
        rag_ids = [s.get("id") for s in similar]
        in_rag = synced.id in rag_ids
        trace_checks["complaint_case_sync"] = {
            "passed": synced.audit_status == "unreviewed"
                      and synced.trust_level == 0.55
                      and not in_rag,
            "synced_id": synced.id,
            "audit_status": synced.audit_status,
            "trust_level": synced.trust_level,
            "in_rag": in_rag,
        }
        if in_rag:
            fail("ComplaintCase unreviewed 节点进入了 RAG")
    else:
        trace_checks["complaint_case_sync"] = {"passed": False, "error": "同步后未找到 KG 节点"}
        fail("ComplaintCase 未同步到 KG")

    # 3d. API 边校验 — 由 pytest 覆盖，此处标记
    trace_checks["references_to_concept_api_rejected"] = {
        "checked": False,
        "note": "由 pytest test_admin_cannot_create_references_to_concept 覆盖（422）",
    }

finally:
    # 清理临时数据
    if tmp_src_id is not None and tmp_tgt_id is not None:
        db.execute(text(f"DELETE FROM kg_edges WHERE source_id={tmp_src_id} AND target_id={tmp_tgt_id}"))
        if tmp_concept_id:
            db.execute(text(f"DELETE FROM kg_edges WHERE source_id={tmp_src_id} AND target_id={tmp_concept_id}"))
        db.execute(text(f"DELETE FROM kg_nodes WHERE id={tmp_src_id}"))
        db.execute(text(f"DELETE FROM kg_nodes WHERE id={tmp_tgt_id}"))
        if tmp_concept_id:
            db.execute(text(f"DELETE FROM kg_nodes WHERE id={tmp_concept_id}"))
    if tmp_cc_id:
        db.execute(text(f"DELETE FROM complaint_cases WHERE id={tmp_cc_id}"))
        db.execute(text(f"DELETE FROM kg_nodes WHERE rule_id='CC-{tmp_cc_id}'"))
    db.commit()

# ═══════════════════════════════════════════════════════════════
# 4. 组装输出
# ═══════════════════════════════════════════════════════════════
snapshot = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "db_url_masked": DB_URL.replace("///", "///<path>") if "///" in DB_URL else DB_URL,
    "statistics": {
        "total_nodes": total_nodes,
        "by_type": by_type,
        "by_status": by_status,
        "total_edges": total_edges,
        "duplicate_edge_count": dup_count,
        "cat_in_regulation_count": cat_in_regulation,
        "cat_concept_count": cat_concept,
        "complaint_case_db_count": complaint_case_total,
        "complaint_case_kg_nodes": complaint_case_nodes,
        "unreviewed_complaint_case_nodes": unreviewed_cc_nodes,
        "rules_total": rules_total,
        "rules_with_any_out_edge": rules_with_out_edge,
        "rule_coverage_ratio": rule_coverage_ratio,
    },
    "rag_samples": rag_samples,
    "trace_checks": trace_checks,
}

print(json.dumps(snapshot, ensure_ascii=False, indent=2))

# ── 退出码 ────────────────────────────────────────────
db.close()
if EXIT_CODE != 0:
    print(f"\n验收失败，退出码 {EXIT_CODE}", file=sys.stderr)
else:
    print("\n验收通过 ✓", file=sys.stderr)
sys.exit(EXIT_CODE)
