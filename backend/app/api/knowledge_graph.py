"""知识图谱 API — v3 增强检索、管理、RAG 上下文接口"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import audit_service
from app.core.security import get_current_user, require_admin
from app.db.database import get_db
from app.models.knowledge_graph import KGNode, KGEdge
from app.services.knowledge_graph import knowledge_graph

router = APIRouter(prefix="/api/kg", tags=["knowledge-graph"])

# ── 分页模型 ────────────────────────────────────────


class PaginatedResult(BaseModel):
    results: list[dict]
    total: int
    limit: int


# ═══════════════════════════════════════════════════════
# 只读接口（所有登录用户）
# ═══════════════════════════════════════════════════════


@router.get("/search")
async def search_kg(
    q: str = Query(default="", description="搜索关键词"),
    node_type: str | None = Query(None, description="节点类型: regulation/case/rule/template"),
    min_trust: float = Query(0.0, ge=0.0, le=1.0, description="最低可信度"),
    audit_status: str | None = Query(None, description="审核状态: unreviewed/verified/flagged/rejected"),
    tags: str | None = Query(None, description="标签过滤"),
    rule_id: str | None = Query(None, description="规则 ID 过滤"),
    jurisdiction: str | None = Query(None, description="管辖范围/平台过滤"),
    limit: int = Query(20, ge=1, le=100, description="返回数量上限"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """搜索知识图谱节点（多维度过滤）

    安全规则:
    - 普通用户不允许查看 rejected 节点。传 audit_status=rejected 返回 403。
    - admin 可以查看所有审核状态。
    - 默认情况下 (audit_status=None)，自动排除 rejected。
    """
    is_admin = user.get("role") == "admin"

    # 普通用户不允许查看 rejected
    if audit_status == "rejected" and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权查看已拒绝的节点",
        )

    results = knowledge_graph.search(
        db,
        query=q,
        node_type=node_type,
        limit=limit,
        min_trust=min_trust,
        audit_status=audit_status,
        tags=tags,
        rule_id=rule_id,
        jurisdiction=jurisdiction,
        is_admin=is_admin,
    )
    return {"query": q, "results": results, "total": len(results)}


@router.get("/related/{node_id}")
async def related_nodes(
    node_id: int,
    relation: str | None = Query(None),
    min_trust: float = Query(0.0, ge=0.0, le=1.0),
    direction: str = Query("outgoing", pattern="^(outgoing|incoming|both)$",
                           description="outgoing=source_id==node_id, incoming=target_id==node_id, both=双向"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """获取关联节点（支持方向过滤）"""
    return {
        "related": knowledge_graph.get_related(db, node_id, relation, min_trust=min_trust, direction=direction)
    }


@router.get("/regulation/{rule_id}")
async def regulation_for_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """查找规则的法规依据"""
    return {"regulations": knowledge_graph.find_regulation_for_rule(db, rule_id)}


@router.get("/cases/{rule_id}")
async def cases_for_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """查找规则的关联案例"""
    return {"cases": knowledge_graph.find_cases_for_rule(db, rule_id)}


@router.get("/similar-cases")
async def similar_cases(
    desc: str = Query(..., description="违规描述"),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """查找相似案例（仅 verified + trust ≥ 阈值）"""
    return {"cases": knowledge_graph.find_similar_cases(db, desc, limit=limit)}


@router.get("/template/{rule_id}")
async def template_for_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """查找规则对应的合规模板"""
    return {"templates": knowledge_graph.find_template_for_rule(db, rule_id)}


@router.get("/rag-context")
async def rag_context(
    rule_id: str = Query(..., description="规则 ID"),
    violation_desc: str = Query(default="", description="违规描述（查不到法规时用于查案例）"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """构建 RAG 上下文 — 用于 LLM 合规审查时的法规/案例参考"""
    contexts = knowledge_graph.build_rag_context(db, rule_id, violation_desc)
    return {"contexts": contexts, "context_count": len(contexts)}


@router.get("/stats")
async def kg_stats(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """获取知识图谱统计信息"""
    return knowledge_graph.get_stats(db)


# ═══════════════════════════════════════════════════════
# 管理接口（仅 admin）
# ═══════════════════════════════════════════════════════


@router.post("/seed")
async def seed_knowledge_graph(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """初始化知识图谱种子数据 — 幂等，仅管理员"""
    count = knowledge_graph.seed_builtin_knowledge(db)
    audit_service.log(
        user_id=int(admin["sub"]),
        action="kg_seed",
        resource="knowledge_graph",
        detail={"seeded_count": count},
    )
    return {"status": "ok", "count": count}


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
    nodes = (
        db.query(KGNode)
        .filter(KGNode.audit_status.in_(["unreviewed", "flagged"]))
        .order_by(KGNode.trust_level.asc())
        .limit(50)
        .all()
    )
    return {
        "nodes": [
            {
                "id": n.id,
                "node_type": n.node_type,
                "title": n.title,
                "source": n.source,
                "rule_id": n.rule_id,
                "trust_level": n.trust_level,
                "audit_status": n.audit_status,
                "content_preview": n.content[:200] if n.content else "",
            }
            for n in nodes
        ]
    }


# ── v3 新增管理接口 ──────────────────────────────────


class NodeCreate(BaseModel):
    node_type: str = Field(..., pattern="^(regulation|case|rule|template)$")
    title: str = Field(..., min_length=1, max_length=512)
    content: str = Field(..., min_length=1)
    source: str = Field(default="")
    source_url: str = Field(default="")
    tags: str = Field(default="")
    rule_id: str | None = None
    jurisdiction: str = Field(default="")
    effective_date: str | None = None
    publish_date: str | None = None
    trust_level: float = Field(default=0.5, ge=0.0, le=1.0)
    audit_status: str = Field(default="unreviewed", pattern="^(unreviewed|verified|flagged|rejected)$")


class NodeUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    source: str | None = None
    source_url: str | None = None
    tags: str | None = None
    rule_id: str | None = None
    jurisdiction: str | None = None
    effective_date: str | None = None
    publish_date: str | None = None
    trust_level: float | None = Field(default=None, ge=0.0, le=1.0)
    audit_status: str | None = Field(default=None, pattern="^(unreviewed|verified|flagged|rejected)$")


@router.post("/node", status_code=status.HTTP_201_CREATED)
async def create_kg_node(
    body: NodeCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """创建 KG 节点 — 仅管理员"""
    from datetime import date

    n = KGNode(
        node_type=body.node_type,
        title=body.title,
        content=body.content,
        source=body.source,
        source_url=body.source_url,
        tags=body.tags,
        rule_id=body.rule_id,
        jurisdiction=body.jurisdiction,
        trust_level=body.trust_level,
        audit_status=body.audit_status,
    )
    if body.effective_date:
        try:
            n.effective_date = date.fromisoformat(body.effective_date)
        except (ValueError, TypeError):
            pass
    if body.publish_date:
        try:
            n.publish_date = date.fromisoformat(body.publish_date)
        except (ValueError, TypeError):
            pass

    db.add(n)
    db.commit()
    db.refresh(n)

    audit_service.log(
        user_id=int(admin["sub"]),
        action="kg_node_create",
        resource="knowledge_graph",
        resource_id=str(n.id),
        detail={"node_type": n.node_type, "title": n.title},
    )

    return {"id": n.id, "title": n.title, "node_type": n.node_type}


@router.put("/node/{node_id}")
async def update_kg_node(
    node_id: int,
    body: NodeUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """更新 KG 节点 — 仅管理员"""
    from datetime import date

    node = db.query(KGNode).filter(KGNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点不存在")

    changes = {}
    for field_name in [
        "title", "content", "source", "source_url", "tags",
        "rule_id", "jurisdiction", "trust_level", "audit_status",
    ]:
        val = getattr(body, field_name, None)
        if val is not None:
            setattr(node, field_name, val)
            changes[field_name] = val

    if body.effective_date is not None:
        try:
            node.effective_date = date.fromisoformat(body.effective_date) if body.effective_date else None
            changes["effective_date"] = body.effective_date
        except (ValueError, TypeError):
            pass
    if body.publish_date is not None:
        try:
            node.publish_date = date.fromisoformat(body.publish_date) if body.publish_date else None
            changes["publish_date"] = body.publish_date
        except (ValueError, TypeError):
            pass

    db.commit()

    audit_service.log(
        user_id=int(admin["sub"]),
        action="kg_node_update",
        resource="knowledge_graph",
        resource_id=str(node_id),
        detail=changes,
    )

    return {"id": node.id, "updated_fields": list(changes.keys())}


@router.delete("/node/{node_id}")
async def delete_kg_node(
    node_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """删除 KG 节点（软删除：设置为 rejected） — 仅管理员"""
    node = db.query(KGNode).filter(KGNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点不存在")

    # 软删除 — 标记为 rejected
    node.audit_status = "rejected"
    node.audited_by = int(admin["sub"])
    node.audited_at = datetime.now(timezone.utc)
    db.commit()

    audit_service.log(
        user_id=int(admin["sub"]),
        action="kg_node_delete",
        resource="knowledge_graph",
        resource_id=str(node_id),
        detail={"title": node.title, "node_type": node.node_type},
    )

    return {"status": "rejected", "id": node_id}


@router.post("/edge", status_code=status.HTTP_201_CREATED)
async def create_kg_edge(
    source_id: int = Query(..., description="源节点 ID"),
    target_id: int = Query(..., description="目标节点 ID"),
    relation: str = Query(..., description="关系类型: references/demonstrated_by/mitigated_by"),
    weight: float = Query(1.0, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """创建 KG 边 — 仅管理员"""
    # 验证两端节点存在
    src = db.query(KGNode).filter(KGNode.id == source_id).first()
    tgt = db.query(KGNode).filter(KGNode.id == target_id).first()
    if not src or not tgt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="源节点或目标节点不存在")

    edge = KGEdge(
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        weight=weight,
    )
    db.add(edge)
    db.commit()
    db.refresh(edge)

    audit_service.log(
        user_id=int(admin["sub"]),
        action="kg_edge_create",
        resource="knowledge_graph",
        resource_id=str(edge.id),
        detail={
            "source_id": source_id,
            "target_id": target_id,
            "relation": relation,
        },
    )

    return {"id": edge.id, "relation": edge.relation}
