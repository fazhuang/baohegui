"""知识图谱 API — v2 新增 trust_level / audit_status 支持"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.audit import audit_service
from app.core.security import get_current_user, require_admin
from app.db.database import get_db
from app.models.knowledge_graph import KGNode
from app.services.knowledge_graph import knowledge_graph

router = APIRouter(prefix="/api/kg", tags=["knowledge-graph"])


@router.get("/search")
async def search_kg(
    q: str = Query(..., description="搜索关键词"),
    node_type: str | None = Query(None, description="节点类型"),
    min_trust: float = Query(0.0, ge=0.0, le=1.0, description="最低可信度"),
    audit_status: str | None = Query(None, description="审核状态过滤"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """搜索知识图谱"""
    results = knowledge_graph.search(
        db, q, node_type, min_trust=min_trust, audit_status=audit_status,
    )
    return {"query": q, "results": results}


@router.get("/related/{node_id}")
async def related_nodes(
    node_id: int,
    relation: str | None = Query(None),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """获取关联节点"""
    return {"related": knowledge_graph.get_related(db, node_id, relation)}


@router.get("/regulation/{rule_id}")
async def regulation_for_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """查找规则的法规依据"""
    return {"regulations": knowledge_graph.find_regulation_for_rule(db, rule_id)}


@router.get("/similar-cases")
async def similar_cases(
    desc: str = Query(..., description="违规描述"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """查找相似案例"""
    return {"cases": knowledge_graph.find_similar_cases(db, desc)}


@router.get("/template/{rule_id}")
async def template_for_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """查找规则对应的合规模板"""
    return {"templates": knowledge_graph.find_template_for_rule(db, rule_id)}


@router.post("/seed")
async def seed_knowledge_graph(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """初始化知识图谱数据 — 仅管理员"""
    count = knowledge_graph.seed_builtin_knowledge(db)
    audit_service.log(
        user_id=int(admin["sub"]),
        action="kg_seed",
        resource="knowledge_graph",
        detail={"count": count},
    )
    return {"status": "ok", "count": count}


# ── v2 审计管理端点 ───────────────────────────────────────

@router.put("/node/{node_id}/audit")
async def audit_kg_node(
    node_id: int,
    trust_level: float = Query(..., ge=0.0, le=1.0),
    audit_status: str = Query(..., pattern="^(unreviewed|verified|flagged|rejected)$"),
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """审核 KG 节点（设置可信度和审核状态） — 仅管理员"""
    node = db.query(KGNode).filter(KGNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点不存在")
    node.trust_level = trust_level
    node.audit_status = audit_status
    node.audited_by = int(admin["sub"])
    node.audited_at = datetime.now(timezone.utc)
    db.commit()

    audit_service.log(
        user_id=int(admin["sub"]),
        action="kg_node_audit",
        resource="knowledge_graph",
        resource_id=str(node_id),
        detail={
            "trust_level": trust_level,
            "audit_status": audit_status,
            "node_type": node.node_type,
            "title": node.title,
        },
    )

    return {
        "id": node.id,
        "trust_level": node.trust_level,
        "audit_status": node.audit_status,
        "audited_by": node.audited_by,
        "audited_at": node.audited_at.isoformat() if node.audited_at else None,
    }


@router.get("/nodes/needing-review")
async def nodes_needing_review(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """列出待审核的 KG 节点 — 仅管理员"""
    nodes = db.query(KGNode).filter(
        KGNode.audit_status.in_(["unreviewed", "flagged"])
    ).order_by(KGNode.trust_level.asc()).limit(50).all()
    return {
        "nodes": [
            {
                "id": n.id, "node_type": n.node_type, "title": n.title,
                "source": n.source, "trust_level": n.trust_level,
                "audit_status": n.audit_status,
                "content_preview": n.content[:200] if n.content else "",
            }
            for n in nodes
        ]
    }
