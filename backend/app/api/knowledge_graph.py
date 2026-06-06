"""知识图谱 API"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.services.knowledge_graph import knowledge_graph

router = APIRouter(prefix="/api/kg", tags=["knowledge-graph"])


@router.get("/search")
async def search_kg(
    q: str = Query(..., description="搜索关键词"),
    node_type: str | None = Query(None, description="节点类型"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """搜索知识图谱"""
    results = knowledge_graph.search(db, q, node_type)
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
    user: dict = Depends(get_current_user),
):
    """初始化知识图谱数据"""
    count = knowledge_graph.seed_builtin_knowledge(db)
    return {"status": "ok", "count": count}
