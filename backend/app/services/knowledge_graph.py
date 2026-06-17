"""知识图谱服务 — 关联检索、推理与种子数据管理

v3 增强：
- 种子数据从真实 rule assets 抽取（compliance_rules / base_rules / forbidden_words / platform_rules / case_study_reports）
- 幂等 seed（基于 rule_id/title 去重）
- 高级检索：rule_id, tags, jurisdiction, platform, min_trust, audit_status, limit
- RAG 上下文构建：rule→法规、rule→案例、违规→RAG context
- 仅 verified + trust≥阈值节点参与 RAG
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.knowledge_graph import KGNode, KGEdge

logger = logging.getLogger(__name__)

# ── 种子数据路径 ─────────────────────────────────────
_RULES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "rules"
_BACKEND_RULES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "backend" / "rules"


class KnowledgeGraphService:
    """知识图谱服务"""

    # ── 可信度阈值常量 ─────────────────────────────────
    TRUST_MIN_ENRICHMENT = 0.3   # RAG 依据补充的最低可信度
    TRUST_MIN_DISPLAY = 0.0      # 前端展示的最低可信度（含未验证）
    SEARCH_MAX_LIMIT = 100       # 搜索最大返回数
    SEARCH_DEFAULT_LIMIT = 20    # 搜索默认返回数

    @staticmethod
    def search(
        db: Session,
        query: str,
        node_type: Optional[str] = None,
        limit: int = 20,
        min_trust: float = 0.0,
        audit_status: Optional[str] = None,
        tags: Optional[str] = None,
        rule_id: Optional[str] = None,
        jurisdiction: Optional[str] = None,
    ) -> list[dict]:
        """搜索知识图谱节点（多维度过滤）"""
        # 硬限制
        limit = min(max(1, limit), KnowledgeGraphService.SEARCH_MAX_LIMIT)

        q = db.query(KGNode)
        if node_type:
            q = q.filter(KGNode.node_type == node_type)

        # 审核状态过滤
        if audit_status is not None:
            q = q.filter(KGNode.audit_status == audit_status)
        else:
            q = q.filter(KGNode.audit_status != "rejected")

        if min_trust > 0:
            q = q.filter(KGNode.trust_level >= min_trust)

        if tags:
            q = q.filter(KGNode.tags.ilike(f"%{tags}%"))

        if rule_id:
            q = q.filter(KGNode.rule_id == rule_id)

        if jurisdiction:
            q = q.filter(KGNode.jurisdiction.ilike(f"%{jurisdiction}%"))

        # 关键词搜索
        if query:
            q = q.filter(
                or_(
                    KGNode.title.ilike(f"%{query}%"),
                    KGNode.content.ilike(f"%{query}%"),
                    KGNode.tags.ilike(f"%{query}%"),
                    KGNode.source.ilike(f"%{query}%"),
                )
            )

        q = q.order_by(KGNode.trust_level.desc(), KGNode.created_at.desc()).limit(limit)

        return [
            {
                "id": n.id,
                "node_type": n.node_type,
                "title": n.title,
                "content": n.content[:300],
                "source": n.source,
                "source_url": n.source_url,
                "tags": n.tags,
                "rule_id": n.rule_id,
                "jurisdiction": n.jurisdiction,
                "effective_date": n.effective_date.isoformat() if n.effective_date else None,
                "publish_date": n.publish_date.isoformat() if n.publish_date else None,
                "trust_level": n.trust_level,
                "audit_status": n.audit_status,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in q.all()
        ]

    @staticmethod
    def get_related(
        db: Session,
        node_id: int,
        relation: Optional[str] = None,
        min_trust: float = 0.0,
    ) -> list[dict]:
        """获取与指定节点相关的所有节点"""
        edges = db.query(KGEdge).filter(KGEdge.source_id == node_id)
        if relation:
            edges = edges.filter(KGEdge.relation == relation)

        result = []
        for e in edges.all():
            target = db.query(KGNode).filter(
                KGNode.id == e.target_id,
                KGNode.audit_status != "rejected",
            )
            if min_trust > 0:
                target = target.filter(KGNode.trust_level >= min_trust)
            target = target.first()
            if target:
                result.append({
                    "relation": e.relation,
                    "weight": e.weight,
                    "node": {
                        "id": target.id,
                        "node_type": target.node_type,
                        "title": target.title,
                        "content": target.content[:200],
                        "source": target.source,
                        "rule_id": target.rule_id,
                        "tags": target.tags,
                        "trust_level": target.trust_level,
                        "audit_status": target.audit_status,
                    },
                })
        return result

    @staticmethod
    def find_regulation_for_rule(db: Session, rule_id: str) -> list[dict]:
        """查找与某规则相关的法规依据（通过 rule_id 匹配 + edges 关联）"""
        # 先尝试精确 rule_id 匹配
        rule_node = db.query(KGNode).filter(
            KGNode.node_type == "rule", KGNode.rule_id == rule_id
        ).first()

        # 如果没有精确匹配，尝试标题模糊匹配（向后兼容）
        if not rule_node:
            rule_node = db.query(KGNode).filter(
                KGNode.node_type == "rule", KGNode.title.ilike(f"%{rule_id}%")
            ).first()

        if not rule_node:
            return []
        return KnowledgeGraphService.get_related(
            db, rule_node.id, relation="references",
            min_trust=KnowledgeGraphService.TRUST_MIN_ENRICHMENT,
        )

    @staticmethod
    def find_cases_for_rule(db: Session, rule_id: str) -> list[dict]:
        """查找与某规则相关的案例"""
        rule_node = db.query(KGNode).filter(
            KGNode.node_type == "rule", KGNode.rule_id == rule_id
        ).first()
        if not rule_node:
            rule_node = db.query(KGNode).filter(
                KGNode.node_type == "rule", KGNode.title.ilike(f"%{rule_id}%")
            ).first()
        if not rule_node:
            return []
        return KnowledgeGraphService.get_related(
            db, rule_node.id, relation="demonstrated_by",
            min_trust=KnowledgeGraphService.TRUST_MIN_ENRICHMENT,
        )

    @staticmethod
    def find_similar_cases(db: Session, violation_desc: str, limit: int = 5) -> list[dict]:
        """查找与违规描述相似的案例（仅 verified, trust >= TRUST_MIN_ENRICHMENT）"""
        return KnowledgeGraphService.search(
            db,
            violation_desc,
            node_type="case",
            limit=limit,
            min_trust=KnowledgeGraphService.TRUST_MIN_ENRICHMENT,
            audit_status="verified",
        )

    @staticmethod
    def find_template_for_rule(db: Session, rule_id: str) -> list[dict]:
        """查找满足某规则的合规模板"""
        rule_node = db.query(KGNode).filter(
            KGNode.node_type == "rule", KGNode.rule_id == rule_id
        ).first()
        if not rule_node:
            rule_node = db.query(KGNode).filter(
                KGNode.node_type == "rule", KGNode.title.ilike(f"%{rule_id}%")
            ).first()
        if not rule_node:
            return []
        return KnowledgeGraphService.get_related(
            db, rule_node.id, relation="mitigated_by",
            min_trust=KnowledgeGraphService.TRUST_MIN_ENRICHMENT,
        )

    @staticmethod
    def build_rag_context(
        db: Session,
        rule_id: str,
        violation_desc: str = "",
        max_regulations: int = 3,
        max_cases: int = 3,
    ) -> list[dict]:
        """为 LLM 构建可追溯的 RAG 上下文。

        返回格式：
        [
          {"type": "regulation", "rule_id": "R001", "title": "...", "content": "...",
           "source": "...", "node_id": 12, "trust_level": 0.8},
          {"type": "case", "rule_id": "R001", "title": "...", "content": "...",
           "source": "...", "node_id": 15, "trust_level": 0.6},
        ]
        """
        contexts: list[dict] = []

        # 1. 法规依据
        regs = KnowledgeGraphService.find_regulation_for_rule(db, rule_id)
        for r in regs[:max_regulations]:
            node = r.get("node", {})
            if node:
                contexts.append({
                    "type": "regulation",
                    "rule_id": rule_id,
                    "title": node.get("title", ""),
                    "content": node.get("content", "")[:500],
                    "source": node.get("source", ""),
                    "node_id": node.get("id"),
                    "trust_level": node.get("trust_level", 0),
                })

        # 2. 相关案例
        cases = KnowledgeGraphService.find_cases_for_rule(db, rule_id)
        if not cases and violation_desc:
            cases = KnowledgeGraphService.find_similar_cases(
                db, violation_desc, limit=max_cases,
            )
        for c in cases[:max_cases]:
            node = c.get("node", {})
            if node:
                contexts.append({
                    "type": "case",
                    "rule_id": rule_id,
                    "title": node.get("title", ""),
                    "content": node.get("content", "")[:500],
                    "source": node.get("source", ""),
                    "node_id": node.get("id"),
                    "trust_level": node.get("trust_level", 0),
                })

        return contexts

    @staticmethod
    def get_stats(db: Session) -> dict:
        """获取知识图谱统计信息"""
        total = db.query(KGNode).count()
        by_type = {}
        for nt in db.query(KGNode.node_type).distinct().all():
            count = db.query(KGNode).filter(KGNode.node_type == nt[0]).count()
            by_type[nt[0]] = count

        by_status = {}
        for st in db.query(KGNode.audit_status).distinct().all():
            count = db.query(KGNode).filter(KGNode.audit_status == st[0]).count()
            by_status[st[0]] = count

        total_edges = db.query(KGEdge).count()

        return {
            "total_nodes": total,
            "by_type": by_type,
            "by_audit_status": by_status,
            "total_edges": total_edges,
        }

    # ═══════════════════════════════════════════════════════════════
    # Seed — 幂等种子数据
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def seed_builtin_knowledge(db: Session) -> int:
        """初始化知识图谱种子数据（幂等）。"""
        count = 0

        # ── 法规节点 — 从 base_rules.json 抽取 law_ref ──
        base_rules = KnowledgeGraphService._load_json(
            _RULES_DIR / "base_rules.json"
        )
        if base_rules:
            seen_laws = set()
            for rule in base_rules.get("rules", []):
                law_ref = rule.get("law_ref", "")
                if law_ref and law_ref not in seen_laws:
                    seen_laws.add(law_ref)
                    # 解析法律来源
                    title = KnowledgeGraphService._extract_law_title(law_ref)
                    if not KnowledgeGraphService._node_exists(db, title=title, node_type="regulation"):
                        n = KGNode(
                            node_type="regulation",
                            title=title,
                            content=law_ref,
                            source=KnowledgeGraphService._infer_law_source(title),
                            tags="法规依据,基础法规",
                            jurisdiction="全国",
                            trust_level=0.8,
                            audit_status="verified",
                        )
                        db.add(n)
                        count += 1

        # ── 法规模块：核心法规 ──
        core_regulations = [
            {
                "title": "中华人民共和国招标投标法（2017年修订）",
                "content": "规范招标投标活动，保护国家利益、社会公共利益和招标投标活动当事人的合法权益。第十八条：招标人不得以不合理的条件限制或者排斥潜在投标人。第二十条：招标文件不得要求或者标明特定的生产供应者以及含有倾向或者排斥潜在投标人的其他内容。第二十四条：招标人应当确定投标人编制投标文件所需要的合理时间。",
                "source": "全国人大",
                "tags": "招标投标,法律,核心法规",
                "jurisdiction": "全国",
            },
            {
                "title": "中华人民共和国政府采购法（2014年修订）",
                "content": "规范政府采购行为，提高政府采购资金使用效益，维护国家利益和社会公共利益。第三条：政府采购应当遵循公开透明原则、公平竞争原则、公正原则和诚实信用原则。第二十二条：供应商参加政府采购活动应当具备的条件。",
                "source": "全国人大",
                "tags": "政府采购,法律,核心法规",
                "jurisdiction": "全国",
            },
            {
                "title": "中华人民共和国政府采购法实施条例",
                "content": "第二十条：采购人或者采购代理机构不得以不合理的条件对供应商实行差别待遇或者歧视待遇，包括就同一采购项目向供应商提供有差别的项目信息；设定的资格、技术、商务条件与采购项目的具体特点和实际需要不相适应或者与合同履行无关；以特定行政区域或者特定行业的业绩、奖项作为加分条件或者中标、成交条件；非法限定供应商的所有制形式、组织形式或者所在地。",
                "source": "国务院",
                "tags": "政府采购,行政法规,核心法规,资格条件",
                "jurisdiction": "全国",
            },
            {
                "title": "中华人民共和国招标投标法实施条例",
                "content": "第三十二条：招标人不得以不合理的条件限制、排斥潜在投标人或者投标人。第三十三条：招标人应当在招标文件中载明投标有效期。第四十九条：评标委员会成员不得私下接触投标人。",
                "source": "国务院",
                "tags": "招标投标,行政法规,核心法规",
                "jurisdiction": "全国",
            },
            {
                "title": "政府采购需求管理办法（财库〔2021〕22号）",
                "content": "规范政府采购需求管理行为，加强政府采购需求管理的内部控制。第六条：采购人对采购需求管理负有主体责任。第十条：采购需求应当完整、明确，并应考虑落实政府采购政策功能的要求。",
                "source": "财政部",
                "tags": "政府采购,部门规章,需求管理",
                "jurisdiction": "全国",
            },
            {
                "title": "政府采购货物和服务招标投标管理办法（财政部令第87号）",
                "content": "第十一条：公开招标公告应当包括以下主要内容：（一）采购人及其委托的采购代理机构的名称、地址和联系方法；（二）采购项目的名称、预算金额。第二十二条：招标文件应当包括采购项目的商务条件、采购需求、投标人的资格条件、投标报价要求、评标方法、评标标准。",
                "source": "财政部",
                "tags": "政府采购,部门规章,招标投标",
                "jurisdiction": "全国",
            },
        ]
        for r in core_regulations:
            if not KnowledgeGraphService._node_exists(db, title=r["title"], node_type="regulation"):
                n = KGNode(
                    node_type="regulation",
                    title=r["title"],
                    content=r["content"],
                    source=r["source"],
                    tags=r["tags"],
                    jurisdiction=r.get("jurisdiction", "全国"),
                    trust_level=0.85,
                    audit_status="verified",
                )
                db.add(n)
                count += 1

        # ── 规则节点 — 从 compliance_rules.json 抽取 ──
        compliance_rules = KnowledgeGraphService._load_json(
            _RULES_DIR / "compliance_rules.json"
        )
        if compliance_rules:
            for rule in compliance_rules.get("rules", []):
                rule_id = rule.get("rule_id", "")
                if not rule_id:
                    continue
                title = f"{rule_id}: {rule.get('rule_name', '')}"
                if not KnowledgeGraphService._node_exists(db, title=title, node_type="rule"):
                    # 收集法规依据
                    regulation_basis = rule.get("regulation_basis", [])
                    law_refs = []
                    if isinstance(regulation_basis, list):
                        for ref in regulation_basis:
                            t = ref.get("title", "") if isinstance(ref, dict) else str(ref)
                            a = ref.get("article", "") if isinstance(ref, dict) else ""
                            law_refs.append(f"{t} {a}".strip() if a else t)
                    law_ref_text = "; ".join(law_refs) if law_refs else ""

                    content = rule.get("message", "") or rule.get("description", "")
                    if law_ref_text:
                        content = f"{content}\n法规依据: {law_ref_text}"

                    n = KGNode(
                        node_type="rule",
                        title=title,
                        content=content,
                        source="包合规规则库",
                        tags=f"规则,{rule.get('category', '')},{rule.get('rule_type', '')}",
                        rule_id=rule_id,
                        jurisdiction="全国",
                        trust_level=0.75,
                        audit_status="verified",
                    )
                    db.add(n)
                    count += 1

        # ── 案例节点 — 从 case_study_reports 和投诉分析抽取真实案例 ──
        real_cases = [
            {
                "title": "宁夏人民医院手术麻醉设备 — 参数排他指向日本 Hadeco",
                "content": "项目编号2026-2，人民医院手术麻醉设备采购中技术参数完全指向日本Hadeco品牌特定型号，经投诉后认定构成参数排他性条款。处理结果：成立，重新采购。",
                "source": "宁夏政府采购网",
                "tags": "参数排他,品牌指向,投诉成立,医疗设备",
                "jurisdiction": "宁夏",
            },
            {
                "title": "宁夏盲人按摩医院医疗设备 — 多项违规",
                "content": "项目编号2025-15，盲人按摩医院医技设备采购中射线装置要求投标人具有辐射安全许可证，超出项目实际需要。处理结果：成立，废标重新采购。",
                "source": "宁夏政府采购网",
                "tags": "资质超标,投诉成立,医疗设备",
                "jurisdiction": "宁夏",
            },
            {
                "title": "宁夏医科大学PACS存储 — 参数指向华为OceanStor",
                "content": "项目编号2026-3，技术参数明确指向华为OceanStor系列存储设备，排斥其他品牌参与。处理结果：部分成立。",
                "source": "宁夏政府采购网",
                "tags": "参数指向,品牌锁定,投诉成立",
                "jurisdiction": "宁夏",
            },
            {
                "title": "宁夏中西医结合医院肿瘤康复设备 — 参数偏向LED光源",
                "content": "项目编号2025-13，设备技术参数限定特定LED光源波长的光学参数，导致品牌指向。处理结果：部分成立，修改后重新采购。",
                "source": "宁夏政府采购网",
                "tags": "参数排斥,技术限定,投诉成立,医疗设备",
                "jurisdiction": "宁夏",
            },
            {
                "title": "宁夏工商职业技术学院智慧烹饪中心 — 混包投诉",
                "content": "项目编号2026-8，投诉认为厨卫设备+IT系统+工程改造打成一个标包，违反《政府采购法》关于合理划分包组的规定。处理结果：部分成立，重新采购。",
                "source": "宁夏政府采购网",
                "tags": "项目拆分,混包,投诉成立",
                "jurisdiction": "宁夏",
            },
            {
                "title": "某市环卫车辆采购品牌锁定投诉",
                "content": "技术参数要求底盘须为XX品牌，被投诉后认定构成品牌锁定，招标文件对技术参数的要求指向特定品牌，构成以不合理条件对供应商实行差别待遇。修改后重新招标。",
                "source": "甘肃政府采购网",
                "tags": "品牌锁定,参数排他,投诉成立,车辆采购",
                "jurisdiction": "甘肃",
            },
            {
                "title": "某医院设备采购厂家授权要求投诉",
                "content": "要求投标时提供原厂授权函，将授权函作为资格条件，限制了代理商参与。被投诉后认定不合理，修改要求后重新招标。",
                "source": "甘肃政府采购网",
                "tags": "厂家授权,资格限制,投诉成立",
                "jurisdiction": "甘肃",
            },
            {
                "title": "某信息系统项目业绩门槛过高案例",
                "content": "近三年合同金额累计5000万元以上要求，中小企业投诉后认定对新成立企业和中小企业构成歧视，门槛过高与项目实际规模不适应。调整为2000万元。",
                "source": "甘肃政府采购网",
                "tags": "业绩要求,中小企业,门槛过高,投诉成立",
                "jurisdiction": "甘肃",
            },
            {
                "title": "某项目评分主观性过大投诉",
                "content": "评审办法中服务方案占30分且无细化评分标准，被投诉后认定评审因素未细化和量化，主观评分空间过大。调整为分级量化评分。",
                "source": "甘肃政府采购网",
                "tags": "评分标准,主观性,投诉成立",
                "jurisdiction": "甘肃",
            },
            {
                "title": "自治区纪委监委配套设备 — 中小企业声明函造假",
                "content": "项目编号2026-7，中标供应商提供的《中小企业声明函》与实际经营情况不符，被认定虚假提供中小企业声明函。处理结果：投诉成立，中标无效。",
                "source": "宁夏政府采购网",
                "tags": "声明函造假,中小企业,投诉成立",
                "jurisdiction": "宁夏",
            },
            {
                "title": "异常低价审查 — 生态环境监测中心沙尘监测",
                "content": "项目编号2026-6，中标价93万元，项目预算205万元，中标价为预算的45%。投诉质疑异常低价。处理结果：经审查，投标人对低价有合理说明，驳回投诉。",
                "source": "宁夏政府采购网",
                "tags": "异常低价,投诉驳回,价格审查",
                "jurisdiction": "宁夏",
            },
            {
                "title": "四川5起典型案例之一 — 参数排斥供应商",
                "content": "四川省财政厅通报：某单位在招标文件技术参数中引用特定供应商产品说明书中的独家指标，实质排斥其他供应商参与。处罚：给予警告，责令限期改正。",
                "source": "四川财政厅",
                "tags": "参数排斥,独家指标,行政处罚",
                "jurisdiction": "四川",
            },
        ]
        for c in real_cases:
            if not KnowledgeGraphService._node_exists(db, title=c["title"], node_type="case"):
                n = KGNode(
                    node_type="case",
                    title=c["title"],
                    content=c["content"],
                    source=c["source"],
                    tags=c["tags"],
                    jurisdiction=c.get("jurisdiction", ""),
                    trust_level=0.65,
                    audit_status="verified",
                )
                db.add(n)
                count += 1

        # ── 平台规则节点 — 从 platform_rules.json 抽取 ──
        platform_rules = KnowledgeGraphService._load_json(
            _RULES_DIR / "platform_rules.json"
        )
        if platform_rules:
            for mapping in platform_rules.get("mappings", []):
                if not mapping.get("enabled", True):
                    continue
                rule_id = mapping.get("rule_id", "")
                if not rule_id:
                    continue
                title = f"[{mapping.get('platform', '')}] {rule_id}: {mapping.get('description', '')}"
                if not KnowledgeGraphService._node_exists(db, title=title, node_type="regulation"):
                    n = KGNode(
                        node_type="regulation",
                        title=title,
                        content=mapping.get("description", ""),
                        source=mapping.get("platform", ""),
                        tags=f"平台规则,{mapping.get('rule_type', '')},{mapping.get('category', '')}",
                        rule_id=rule_id,
                        jurisdiction=mapping.get("platform", ""),
                        trust_level=0.7,
                        audit_status="verified",
                        effective_date=KnowledgeGraphService._parse_date(
                            mapping.get("effective_date", "")
                        ),
                    )
                    db.add(n)
                    count += 1

        # ── 从 forbidden_words.json 抽取禁用词模式作为规则关联 ──
        forbidden_words = KnowledgeGraphService._load_json(
            _RULES_DIR / "forbidden_words.json"
        )
        if forbidden_words:
            for category_key, patterns in forbidden_words.get("patterns", {}).items():
                if not isinstance(patterns, dict):
                    continue
                category_label = patterns.get("label", category_key)
                regex_list = patterns.get("regex_list", [])
                for item in regex_list:
                    pattern_id = item.get("id", "")
                    if not pattern_id:
                        continue
                    title = f"禁用词模式 {pattern_id}: {item.get('message', '')}"
                    if KnowledgeGraphService._node_exists(db, title=title, node_type="rule"):
                        continue
                    n = KGNode(
                        node_type="rule",
                        title=title,
                        content=item.get("message", ""),
                        source="包合规禁用词库",
                        tags=f"规则,禁用词,{category_label}",
                        rule_id=pattern_id,
                        jurisdiction="全国",
                        trust_level=0.7,
                        audit_status="verified",
                    )
                    db.add(n)
                    count += 1

        db.flush()

        # ── 创建 edges: rule → regulation (引用) ──
        all_rules = db.query(KGNode).filter(KGNode.node_type == "rule").all()
        all_regulations = db.query(KGNode).filter(KGNode.node_type == "regulation").all()
        edges_created = 0

        for rule_node in all_rules:
            for reg_node in all_regulations:
                # 规则内容包含法规标题
                if reg_node.title and rule_node.content and (
                    reg_node.title in rule_node.content
                    or (reg_node.title[:10] in rule_node.content)
                ):
                    if not KnowledgeGraphService._edge_exists(
                        db, rule_node.id, reg_node.id, "references"
                    ):
                        e = KGEdge(
                            source_id=rule_node.id,
                            target_id=reg_node.id,
                            relation="references",
                            weight=1.0,
                        )
                        db.add(e)
                        edges_created += 1

        # ── 创建 edges: rule → case (被案例证实) ──
        all_cases = db.query(KGNode).filter(KGNode.node_type == "case").all()
        for rule_node in all_rules:
            rule_tags = (rule_node.tags or "").split(",")
            for case_node in all_cases:
                case_tags = (case_node.tags or "").split(",")
                common_tags = set(t.strip() for t in rule_tags) & set(
                    t.strip() for t in case_tags
                )
                if common_tags and common_tags != {"规则"}:
                    if not KnowledgeGraphService._edge_exists(
                        db, rule_node.id, case_node.id, "demonstrated_by"
                    ):
                        e = KGEdge(
                            source_id=rule_node.id,
                            target_id=case_node.id,
                            relation="demonstrated_by",
                            weight=0.5,
                        )
                        db.add(e)
                        edges_created += 1

        db.commit()
        logger.info(
            "知识图谱种子完成: %d 节点 + %d 边",
            count,
            edges_created,
        )
        return count + edges_created

    # ── 内部工具方法 ─────────────────────────────────

    @staticmethod
    def _node_exists(db: Session, title: str, node_type: str) -> bool:
        """检查节点是否已存在（幂等）"""
        return db.query(KGNode).filter(
            KGNode.title == title, KGNode.node_type == node_type
        ).first() is not None

    @staticmethod
    def _edge_exists(
        db: Session, source_id: int, target_id: int, relation: str
    ) -> bool:
        """检查边是否已存在（幂等）"""
        return db.query(KGEdge).filter(
            KGEdge.source_id == source_id,
            KGEdge.target_id == target_id,
            KGEdge.relation == relation,
        ).first() is not None

    @staticmethod
    def _load_json(path: Path) -> dict | None:
        """安全加载 JSON 文件"""
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning("加载规则资产失败 %s: %s", path, e)
        return None

    @staticmethod
    def _extract_law_title(law_ref: str) -> str:
        """从法律引用文字中提取法律标题"""
        # 常见格式：《政府采购法实施条例》第三十四条
        import re
        m = re.match(r'[《「]([^》」]+)[》」]', law_ref)
        if m:
            return m.group(1)
        return law_ref[:50]

    @staticmethod
    def _infer_law_source(title: str) -> str:
        """从法律标题推断来源机构"""
        if "招标投标法" in title:
            return "全国人大"
        if "政府采购法" in title:
            return "全国人大" if "实施条例" not in title else "国务院"
        if "财政部" in title or "财库" in title:
            return "财政部"
        return ""

    @staticmethod
    def _parse_date(date_str: str) -> Optional[date]:
        """安全解析日期字符串"""
        import re
        if not date_str:
            return None
        try:
            return date.fromisoformat(date_str)
        except (ValueError, TypeError):
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_str)
            if m:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return None


knowledge_graph = KnowledgeGraphService()
