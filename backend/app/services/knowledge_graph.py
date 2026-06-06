"""知识图谱服务 — 关联检索与推理"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.knowledge_graph import KGNode, KGEdge

logger = logging.getLogger(__name__)


class KnowledgeGraphService:
    """知识图谱服务"""

    @staticmethod
    def search(db: Session, query: str, node_type: Optional[str] = None, limit: int = 20) -> list[dict]:
        """全文搜索知识图谱节点"""
        q = db.query(KGNode)
        if node_type:
            q = q.filter(KGNode.node_type == node_type)
        q = q.filter(
            or_(
                KGNode.title.ilike(f"%{query}%"),
                KGNode.content.ilike(f"%{query}%"),
                KGNode.tags.ilike(f"%{query}%"),
            )
        ).limit(limit)
        return [{"id": n.id, "node_type": n.node_type, "title": n.title,
                 "content": n.content[:300], "source": n.source, "tags": n.tags} for n in q.all()]

    @staticmethod
    def get_related(db: Session, node_id: int, relation: Optional[str] = None) -> list[dict]:
        """获取与指定节点相关的所有节点"""
        edges = db.query(KGEdge).filter(KGEdge.source_id == node_id)
        if relation:
            edges = edges.filter(KGEdge.relation == relation)

        result = []
        for e in edges.all():
            target = db.query(KGNode).filter(KGNode.id == e.target_id).first()
            if target:
                result.append({
                    "relation": e.relation,
                    "weight": e.weight,
                    "node": {"id": target.id, "node_type": target.node_type,
                            "title": target.title, "content": target.content[:200]},
                })
        return result

    @staticmethod
    def find_regulation_for_rule(db: Session, rule_id: str) -> list[dict]:
        """查找与某规则相关的法规依据"""
        node = db.query(KGNode).filter(
            KGNode.node_type == "rule", KGNode.title.ilike(f"%{rule_id}%")
        ).first()
        if not node:
            return []
        return KnowledgeGraphService.get_related(db, node.id, relation="references")

    @staticmethod
    def find_similar_cases(db: Session, violation_desc: str, limit: int = 5) -> list[dict]:
        """查找与违规描述相似的已判决案例"""
        return KnowledgeGraphService.search(db, violation_desc, node_type="case", limit=limit)

    @staticmethod
    def find_template_for_rule(db: Session, rule_id: str) -> list[dict]:
        """查找满足某规则的合规模板"""
        node = db.query(KGNode).filter(
            KGNode.node_type == "rule", KGNode.title.ilike(f"%{rule_id}%")
        ).first()
        if not node:
            return []
        return KnowledgeGraphService.get_related(db, node.id, relation="satisfies")

    @staticmethod
    def seed_builtin_knowledge(db: Session) -> int:
        """初始化内置知识图谱数据（法规、案例、规则关联）"""
        count = 0

        # Check if already seeded
        existing = db.query(KGNode).first()
        if existing:
            return 0

        # Seed core regulations
        regulations = [
            {"type": "regulation", "title": "招标投标法", "content": "中华人民共和国招标投标法（2017年修订）全文...", "source": "全国人大", "tags": "招标投标,法律,基础"},
            {"type": "regulation", "title": "政府采购法", "content": "中华人民共和国政府采购法（2014年修订）全文...", "source": "全国人大", "tags": "政府采购,法律,基础"},
            {"type": "regulation", "title": "政府采购法实施条例", "content": "政府采购法实施条例全文...", "source": "国务院", "tags": "政府采购,行政法规"},
            {"type": "regulation", "title": "招标投标法实施条例", "content": "招标投标法实施条例全文...", "source": "国务院", "tags": "招标投标,行政法规"},
            {"type": "regulation", "title": "政府采购需求管理办法", "content": "政府采购需求管理办法（财库〔2021〕22号）全文...", "source": "财政部", "tags": "政府采购,部门规章"},
        ]

        for r in regulations:
            n = KGNode(node_type=r["type"], title=r["title"], content=r["content"],
                      source=r["source"], tags=r["tags"])
            db.add(n)
            count += 1

        # Seed typical cases from 558 complaint cases
        cases = [
            {"type": "case", "title": "品牌锁定投诉案例", "content": "某市环卫车辆采购中，技术参数要求'底盘须为XX品牌'，被投诉后认定构成品牌锁定，修改后重新招标。", "source": "甘肃政府采购网", "tags": "品牌锁定,参数排他,投诉成立"},
            {"type": "case", "title": "厂家授权投诉案例", "content": "某医院设备采购要求'投标时提供原厂授权函'，代理商投诉后认定不合理，取消该要求后重新招标。", "source": "甘肃政府采购网", "tags": "厂家授权,资格限制,投诉成立"},
            {"type": "case", "title": "业绩门槛过高案例", "content": "某信息系统项目要求'近三年合同金额累计5000万元以上'，中小企业投诉后认定门槛过高，调整为2000万元。", "source": "甘肃政府采购网", "tags": "业绩要求,中小企业,投诉成立"},
            {"type": "case", "title": "评分主观性投诉案例", "content": "某项目评审办法中'服务方案'占30分且无细化标准，被投诉后调整为分级量化评分。", "source": "甘肃政府采购网", "tags": "评分标准,主观性,投诉成立"},
        ]

        for c in cases:
            n = KGNode(node_type=c["type"], title=c["title"], content=c["content"],
                      source=c["source"], tags=c["tags"])
            db.add(n)
            count += 1

        # Seed rule nodes and link them to regulations
        rules_data = [
            {"id": "R107", "title": "品牌锁定检测规则", "desc": "检测技术参数中的品牌锁定风险", "regulation": "政府采购法实施条例 第二十条"},
            {"id": "R101", "title": "厂家授权检测规则", "desc": "检测厂家授权函要求是否合理", "regulation": "政府采购法实施条例 第二十条"},
            {"id": "AI-BIAS-004", "title": "参数指向性检测规则", "desc": "检测参数组合后是否指向唯一供应商", "regulation": "政府采购法 第三条"},
        ]

        for rd in rules_data:
            n = KGNode(node_type="rule", title=rd["title"], content=rd["desc"],
                      source="包合规系统", tags=f"规则,{rd['id']}")
            db.add(n)
            count += 1

        db.flush()  # Get IDs for edge creation

        # Create edges: rules → regulations
        for rd in rules_data:
            rule_node = db.query(KGNode).filter(
                KGNode.node_type == "rule", KGNode.tags.ilike(f"%{rd['id']}%")
            ).first()
            reg_node = db.query(KGNode).filter(
                KGNode.node_type == "regulation", KGNode.title.ilike(f"%{rd['regulation'].split(' ')[0]}%")
            ).first()
            if rule_node and reg_node:
                edge = KGEdge(source_id=rule_node.id, target_id=reg_node.id,
                            relation="references", weight=1.0)
                db.add(edge)
                count += 1

        db.commit()
        logger.info("知识图谱初始化完成: %d 条记录", count)
        return count


knowledge_graph = KnowledgeGraphService()
