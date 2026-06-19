"""知识图谱服务 — 关联检索、推理与种子数据管理

v4 增强：
- 全面种子数据填充：base_rules / compliance_rules / industry_rules / platform_rules / parameter_bias / forbidden_words / complaint_cases / project_categories
- 幂等 seed（基于 rule_id/title 去重）
- 高级检索：rule_id, tags, jurisdiction, platform, min_trust, audit_status, limit
- RAG 上下文构建：rule→法规、rule→案例、违规→RAG context
- 仅 verified + trust≥阈值节点参与 RAG
- 增强边创建：法规条文号匹配、关键词匹配、case→regulation
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re as _re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.knowledge_graph import KGNode, KGEdge
from app.models.complaint_case import ComplaintCase

logger = logging.getLogger(__name__)

# ── 种子数据路径 ─────────────────────────────────────
def _resolve_rules_dir() -> Path:
    configured = os.environ.get("BHG_RULES_DIR")
    if configured:
        return Path(configured)

    container_rules = Path("/app/rules")
    if container_rules.exists():
        return container_rules

    return Path(__file__).resolve().parent.parent.parent.parent / "rules"


_RULES_DIR = _resolve_rules_dir()


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
        offset: int = 0,
        min_trust: float = 0.0,
        audit_status: Optional[str] = None,
        tags: Optional[str] = None,
        rule_id: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        is_admin: bool = False,
    ) -> tuple:
        """搜索知识图谱节点（多维度过滤），返回 (results, total)。

        安全规则:
        - 所有用户默认排除 rejected（包括 admin）。rejected 节点只能在显式传 audit_status=rejected 时查看。
        - Phase 1: 非 admin 调用时，服务层默认只显示 audit_status='verified' 的节点。
          非 admin 显式传 unreviewed/flagged 由 API 层 403 拒绝，本层收到时按请求值过滤。
        - admin 可以显式传 audit_status=rejected 查看已拒绝节点。
        """
        # 硬限制
        limit = min(max(1, limit), KnowledgeGraphService.SEARCH_MAX_LIMIT)
        offset = max(0, offset)

        q = db.query(KGNode)
        if node_type:
            q = q.filter(KGNode.node_type == node_type)

        # 审核状态过滤
        if audit_status is not None:
            q = q.filter(KGNode.audit_status == audit_status)
        else:
            # 默认：非管理员只能看到 verified
            if not is_admin:
                q = q.filter(KGNode.audit_status == "verified")
            else:
                # 所有用户（包括 admin）默认排除 rejected
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

        # 先取总数（分页前，不受 offset/limit 影响）
        total = q.count()

        q = q.order_by(KGNode.trust_level.desc(), KGNode.created_at.desc())
        q = q.offset(offset).limit(limit)

        results = [
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
        return results, total

    @staticmethod
    def get_related(
        db: Session,
        node_id: int,
        relation: Optional[str] = None,
        min_trust: float = 0.0,
        direction: str = "outgoing",
        target_type: Optional[str] = None,
    ) -> list[dict]:
        """获取与指定节点相关的所有节点。

        direction:
          - "outgoing": edges where source_id == node_id (默认，向后兼容)
          - "incoming": edges where target_id == node_id (谁引用了此节点)
          - "both": 双向

        target_type: 可选，过滤目标节点类型（如 "regulation" 确保 RAG 只返回法规）

        Phase 1 可见性：仅返回 target audit_status='verified' 的节点（除非是管理员）。
        """
        if direction == "incoming":
            edges = db.query(KGEdge).filter(KGEdge.target_id == node_id)
        elif direction == "both":
            from sqlalchemy import or_
            edges = db.query(KGEdge).filter(
                or_(KGEdge.source_id == node_id, KGEdge.target_id == node_id)
            )
        else:
            edges = db.query(KGEdge).filter(KGEdge.source_id == node_id)

        if relation:
            edges = edges.filter(KGEdge.relation == relation)

        result = []
        for e in edges.all():
            # For incoming edges, the "target" we want to show is actually the source of the edge
            if direction == "incoming":
                target_id = e.source_id
                actual_relation = f"← {e.relation}"  # flip label for clarity
            else:
                target_id = e.target_id
                actual_relation = e.relation

            target = db.query(KGNode).filter(
                KGNode.id == target_id,
                KGNode.audit_status == "verified",  # Phase 1: 仅已审核
            )
            if target_type:
                target = target.filter(KGNode.node_type == target_type)
            if min_trust > 0:
                target = target.filter(KGNode.trust_level >= min_trust)
            target = target.first()
            if target:
                result.append({
                    "relation": actual_relation,
                    "weight": e.weight,
                    "node": {
                        "id": target.id,
                        "node_type": target.node_type,
                        "title": target.title,
                        "content": target.content[:200],
                        "source": target.source,
                        "source_url": target.source_url or None,
                        "rule_id": target.rule_id,
                        "tags": target.tags,
                        "jurisdiction": target.jurisdiction or None,
                        "effective_date": target.effective_date.isoformat() if target.effective_date else None,
                        "publish_date": target.publish_date.isoformat() if target.publish_date else None,
                        "created_at": target.created_at.isoformat() if target.created_at else None,
                        "trust_level": target.trust_level,
                        "audit_status": target.audit_status,
                    },
                })
        return result

    @staticmethod
    def _find_trusted_rule_node(db: Session, rule_id: str) -> KGNode | None:
        """查找可信的 rule 节点（起点也必须满足 trust + audit 要求）。

        规则：
        - 仅返回 audit_status == "verified" 且 trust_level >= TRUST_MIN_ENRICHMENT 的节点
        - 精确 rule_id 匹配时，优先选择有 references 或 demonstrated_by 出边的节点
        - 其次按 trust_level desc、出边数量 desc、created_at desc 排序
        - 标题模糊匹配仅作为 fallback
        - 如果发现匹配节点但不满足可信条件，返回 None（不允许绕过）
        """
        TRUST = KnowledgeGraphService.TRUST_MIN_ENRICHMENT

        # 精确 rule_id 匹配 — 已审核 + 高信任
        candidates = db.query(KGNode).filter(
            KGNode.node_type == "rule",
            KGNode.rule_id == rule_id,
            KGNode.audit_status == "verified",
            KGNode.trust_level >= TRUST,
        ).all()

        if candidates:
            # 按优先级排序：有出边 > 无出边，trust 高的优先，边数多的优先
            scored = []
            for node in candidates:
                ref_count = db.query(KGEdge).filter(
                    KGEdge.source_id == node.id,
                    KGEdge.relation.in_(["references", "demonstrated_by"]),
                ).count()
                scored.append((node, ref_count))
            # 排序：ref_count desc, trust_level desc, created_at desc (created_at 越大越新)
            scored.sort(key=lambda x: (-x[1], -x[0].trust_level, -(x[0].created_at.timestamp() if x[0].created_at else 0)))
            return scored[0][0]

        # 标题模糊匹配（向后兼容）— 同样需要可信 + 排序
        candidates = db.query(KGNode).filter(
            KGNode.node_type == "rule",
            KGNode.title.ilike(f"%{rule_id}%"),
            KGNode.audit_status == "verified",
            KGNode.trust_level >= TRUST,
        ).all()

        if candidates:
            scored = []
            for node in candidates:
                ref_count = db.query(KGEdge).filter(
                    KGEdge.source_id == node.id,
                    KGEdge.relation.in_(["references", "demonstrated_by"]),
                ).count()
                scored.append((node, ref_count))
            scored.sort(key=lambda x: (-x[1], -x[0].trust_level, -(x[0].created_at.timestamp() if x[0].created_at else 0)))
            return scored[0][0]

        return None

    @staticmethod
    def find_regulation_for_rule(db: Session, rule_id: str) -> list[dict]:
        """查找与某规则相关的法规依据（仅可信 rule 起点 → 可信 regulation 目标）

        强制过滤 target_type="regulation"，确保 concept 节点不会混入 RAG 法规依据。
        """
        rule_node = KnowledgeGraphService._find_trusted_rule_node(db, rule_id)
        if not rule_node:
            return []
        return KnowledgeGraphService.get_related(
            db, rule_node.id, relation="references",
            min_trust=KnowledgeGraphService.TRUST_MIN_ENRICHMENT,
            target_type="regulation",
        )

    @staticmethod
    def find_cases_for_rule(db: Session, rule_id: str) -> list[dict]:
        """查找与某规则相关的案例（仅可信 rule 起点 → 可信 target）"""
        rule_node = KnowledgeGraphService._find_trusted_rule_node(db, rule_id)
        if not rule_node:
            return []
        return KnowledgeGraphService.get_related(
            db, rule_node.id, relation="demonstrated_by",
            min_trust=KnowledgeGraphService.TRUST_MIN_ENRICHMENT,
        )

    @staticmethod
    def find_similar_cases(db: Session, violation_desc: str, limit: int = 5) -> list[dict]:
        """查找与违规描述相似的案例（仅 verified, trust >= TRUST_MIN_ENRICHMENT）"""
        results, _ = KnowledgeGraphService.search(
            db,
            violation_desc,
            node_type="case",
            limit=limit,
            min_trust=KnowledgeGraphService.TRUST_MIN_ENRICHMENT,
            audit_status="verified",
        )
        return results

    @staticmethod
    def find_template_for_rule(db: Session, rule_id: str) -> list[dict]:
        """查找满足某规则的合规模板（仅可信 rule 起点）"""
        rule_node = KnowledgeGraphService._find_trusted_rule_node(db, rule_id)
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
           "source": "...", "source_url": "...", "node_id": 12, "trust_level": 0.8,
           "relation": "references", "edge_weight": 1.0},
          {"type": "case", "rule_id": "R001", "title": "...", "content": "...",
           "source": "...", "source_url": "...", "node_id": 15, "trust_level": 0.6,
           "relation": "demonstrated_by", "edge_weight": 1.0},
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
                    "source": node.get("source") or None,
                    "source_url": node.get("source_url") or None,
                    "node_id": node.get("id"),
                    "trust_level": node.get("trust_level", 0),
                    "effective_date": node.get("effective_date") or None,
                    "publish_date": node.get("publish_date") or None,
                    "relation": r.get("relation", ""),
                    "edge_weight": r.get("weight", 1.0),
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
                    "source": node.get("source") or None,
                    "source_url": node.get("source_url") or None,
                    "node_id": node.get("id"),
                    "trust_level": node.get("trust_level", 0),
                    "effective_date": node.get("effective_date") or None,
                    "publish_date": node.get("publish_date") or None,
                    "relation": c.get("relation", ""),
                    "edge_weight": c.get("weight", 1.0),
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
        """初始化知识图谱种子数据（幂等）。

        数据来源（按导入顺序）：
        1. base_rules.json law_ref → regulation 节点
        2. 核心法规（6 部硬编码）
        3. compliance_rules.json → rule 节点
        4. base_rules.json rules → rule 节点（NEW）
        5. industry/*.json → rule 节点（NEW）
        6. platforms/*.json additional_rules → rule 节点（NEW）
        7. parameter_bias_rules.json → rule 节点（NEW）
        8. 硬编码案例（12 个真实案例）
        9. complaint_cases 表同步 → case 节点（NEW）
        10. platform_rules.json → regulation 节点
        11. forbidden_words.json → rule 节点
        12. project_categories.json → concept 节点（NEW）
        13. 边创建：rule→regulation / rule→case / case→regulation
        """
        count = 0

        # ── Phase 1: 法规节点 — 从 base_rules.json 抽取 law_ref ──
        base_rules = KnowledgeGraphService._load_json(
            _RULES_DIR / "base_rules.json"
        )
        if base_rules:
            seen_law_titles = set()
            for rule in base_rules.get("rules", []):
                law_ref = rule.get("law_ref", "")
                if law_ref:
                    title = KnowledgeGraphService._extract_law_title(law_ref)
                    if title in seen_law_titles:
                        continue
                    seen_law_titles.add(title)
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

        db.flush()

        # ── Phase 2: 核心法规 ──
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

        db.flush()

        # ── Phase 3: 规则节点 — compliance_rules.json ──
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

        db.flush()

        # ── Phase 4: 规则节点 — base_rules.json 57条基础规则 (NEW) ──
        if base_rules:
            _prefix_category = {
                "SEC": "章节完整性", "KEY": "关键字检测",
                "FORB": "禁用词", "FMT": "格式要求",
            }
            for rule in base_rules.get("rules", []):
                rule_id = rule.get("id", "")
                if not rule_id:
                    continue
                if KnowledgeGraphService._node_exists_by_rule_id(db, rule_id, "rule"):
                    continue

                prefix = rule_id.split("-")[0] if "-" in rule_id else ""
                category_tag = _prefix_category.get(prefix, "基础规则")

                content_parts = [
                    f"类型: {rule.get('type', '')}",
                    f"目标: {rule.get('target', '')}",
                    f"权重: {rule.get('weight', '')}",
                    f"描述: {rule.get('description', '')}",
                ]
                if rule.get("law_ref"):
                    content_parts.append(f"法规依据: {rule.get('law_ref', '')}")
                if rule.get("suggestion"):
                    content_parts.append(f"修改建议: {rule.get('suggestion', '')}")
                if rule.get("pattern"):
                    content_parts.append(f"匹配模式: {rule.get('pattern', '')}")
                if rule.get("keyword"):
                    content_parts.append(f"关键词: {rule.get('keyword', '')}")

                n = KGNode(
                    node_type="rule",
                    title=f"{rule_id}: {rule.get('description', '')[:80]}",
                    content="\n".join(content_parts),
                    source="包合规基础规则库",
                    tags=f"规则,基础规则,{category_tag},{rule.get('type', '')},{rule.get('severity', '')}",
                    rule_id=rule_id,
                    jurisdiction="全国",
                    trust_level=0.75,
                    audit_status="verified",
                )
                db.add(n)
                count += 1

        db.flush()

        # ── Phase 5: 规则节点 — industry/*.json 行业细分规则 (NEW) ──
        industry_dir = _RULES_DIR / "industry"
        _industry_names = {
            "construction": "房屋建筑工程", "gov": "政府采购", "municipal": "市政工程",
            "highway": "公路工程", "railway": "铁路工程", "water": "水利水电工程",
            "electric_power": "电力工程", "communication": "通信工程",
            "petrochemical": "石油化工工程", "port_waterway": "港口与航道工程",
            "mine": "矿山工程", "env_protection": "环保工程", "landscaping": "园林绿化工程",
            "agriculture": "农林牧渔业", "medical_health": "医疗卫生",
            "education_culture": "教育文体", "it": "信息技术", "healthcare": "医疗采购",
        }
        if industry_dir.exists():
            for fname in sorted(os.listdir(industry_dir)):
                if not fname.endswith(".json"):
                    continue
                ind_data = KnowledgeGraphService._load_json(industry_dir / fname)
                if not ind_data:
                    continue
                ind_name = ind_data.get("industry",
                    _industry_names.get(fname.replace(".json", ""), fname))
                for rule in ind_data.get("rules", []):
                    rule_id = rule.get("id", "")
                    if not rule_id:
                        continue
                    if KnowledgeGraphService._node_exists_by_rule_id(db, rule_id, "rule"):
                        continue

                    content_parts = [
                        f"行业: {ind_name}",
                        f"类型: {rule.get('type', '')}",
                        f"描述: {rule.get('description', '')}",
                    ]
                    if rule.get("law_ref"):
                        content_parts.append(f"法规依据: {rule.get('law_ref', '')}")
                    if rule.get("suggestion"):
                        content_parts.append(f"修改建议: {rule.get('suggestion', '')}")
                    if rule.get("keyword"):
                        content_parts.append(f"关键词: {rule.get('keyword', '')}")

                    n = KGNode(
                        node_type="rule",
                        title=f"[{ind_name}] {rule_id}: {rule.get('description', '')[:60]}",
                        content="\n".join(content_parts),
                        source="包合规行业规则库",
                        tags=f"规则,行业规则,{ind_name},{rule.get('type', '')},{rule.get('category', '')}",
                        rule_id=rule_id,
                        jurisdiction="全国",
                        trust_level=0.65,
                        audit_status="verified",
                    )
                    db.add(n)
                    count += 1

        db.flush()

        # ── Phase 6: 规则节点 — platforms/*.json 平台特定规则 (NEW) ──
        platforms_dir = _RULES_DIR / "platforms"
        if platforms_dir.exists():
            for fname in sorted(os.listdir(platforms_dir)):
                if not fname.endswith(".json"):
                    continue
                plat_data = KnowledgeGraphService._load_json(platforms_dir / fname)
                if not plat_data:
                    continue
                plat_name = plat_data.get("name", fname)
                plat_id = plat_data.get("platform", "")
                for rule in plat_data.get("additional_rules", []):
                    rule_id = rule.get("rule_id", "")
                    if not rule_id:
                        continue
                    if KnowledgeGraphService._node_exists_by_rule_id(db, rule_id, "rule"):
                        continue

                    reg_basis = rule.get("regulation_basis", [])
                    law_ref_text = "; ".join(
                        f"{r.get('title', '')} {r.get('article', '')}"
                        for r in reg_basis
                    ) if isinstance(reg_basis, list) else ""

                    content_parts = [
                        f"平台: {plat_name}",
                        f"类型: {rule.get('rule_type', '')}",
                        f"描述: {rule.get('description', '')}",
                        f"风险等级: {rule.get('risk_level', '')}",
                    ]
                    if law_ref_text:
                        content_parts.append(f"法规依据: {law_ref_text}")
                    if rule.get("suggestion"):
                        content_parts.append(f"修改建议: {rule.get('suggestion', '')}")

                    n = KGNode(
                        node_type="rule",
                        title=f"[{plat_name}] {rule_id}: {rule.get('rule_name', '')}",
                        content="\n".join(content_parts),
                        source=plat_name,
                        tags=f"规则,平台规则,{plat_name},{rule.get('category', '')},{rule.get('rule_type', '')}",
                        rule_id=rule_id,
                        jurisdiction=plat_id or plat_name,
                        trust_level=0.70,
                        audit_status="verified",
                    )
                    db.add(n)
                    count += 1

        db.flush()

        # ── Phase 7: 规则节点 — parameter_bias_rules.json 参数倾向检测 (NEW) ──
        param_bias = KnowledgeGraphService._load_json(
            _RULES_DIR / "parameter_bias_rules.json"
        )
        if param_bias:
            for pattern_key, pattern in param_bias.get("violation_patterns", {}).items():
                rule_id = pattern.get("rule_id", "")
                if not rule_id:
                    continue
                if KnowledgeGraphService._node_exists_by_rule_id(db, rule_id, "rule"):
                    continue

                content_parts = [
                    f"检测模式: {pattern_key}",
                    f"严重度: {pattern.get('severity', '')} ({pattern.get('risk_level', '')})",
                    f"描述: {pattern.get('description', '')}",
                    f"检测逻辑: {pattern.get('check_logic', '')}",
                    f"修改建议: {pattern.get('suggestion', '')}",
                    f"检测字段: {', '.join(pattern.get('check_fields', []))}",
                ]
                if pattern.get("keywords"):
                    content_parts.append(
                        f"关键词: {', '.join(pattern['keywords'][:15])}"
                    )

                n = KGNode(
                    node_type="rule",
                    title=f"参数倾向检测 {rule_id}: {pattern.get('description', '')[:70]}",
                    content="\n".join(content_parts),
                    source="包合规参数倾向检测规则库",
                    tags=f"规则,参数倾向检测,{pattern.get('severity', '')},{pattern.get('risk_level', '')}",
                    rule_id=rule_id,
                    jurisdiction="全国",
                    trust_level=0.70,
                    audit_status="verified",
                )
                db.add(n)
                count += 1

        db.flush()

        # ── Phase 8: 案例节点 — 硬编码真实案例 ──
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
            # ── 陕西典型案例 ──
            {
                "title": "陕西铜川陈炉镇非遗保护设备 — 内部型号锁定+原厂授权",
                "content": "铜川陈炉镇非遗保护设备采购，14项投诉中9项成立：品牌指向+内部型号+原厂授权。3D陶瓷打印机参数锁定微瓷科技，构成实质性品牌锁定。处理结果：成立，中标无效。",
                "source": "陕西政府采购网",
                "tags": "品牌锁定,内部型号,厂家授权,投诉成立",
                "jurisdiction": "陕西",
            },
            {
                "title": "陕西神木水质提升工程 — 参数排他+歧视中小企业",
                "content": "神木水质提升工程招标文件参数量身定做，且有授权要求，对企业规模和本地服务提出不合理门槛，歧视中小企业。处理结果：成立，重新采购。",
                "source": "陕西政府采购网",
                "tags": "参数排斥,中小企业歧视,授权锁定,投诉成立",
                "jurisdiction": "陕西",
            },
            {
                "title": "陕西西安市第三医院机器人手术系统 — 参数倾向+评审未量化",
                "content": "西安市第三医院机器人手术系统采购，技术参数具有品牌倾向，且评审标准主观性过强、未细化量化。处理结果：成立，已修改招标文件。",
                "source": "陕西政府采购网",
                "tags": "参数倾向,评分标准,评审未量化,投诉成立",
                "jurisdiction": "陕西",
            },
            # ── 青海典型案例 ──
            {
                "title": "青海职业技术大学语言文字基地 — 废止标准+评分未量化",
                "content": "青海职业技术大学语言文字基地设备采购，引用已废止标准GB18584-2001和不存在的标准GB2423.6-1995，且评分标准未量化。处理结果：全部成立，重新采购。",
                "source": "青海政府采购网",
                "tags": "废止标准,评分未量化,投诉成立",
                "jurisdiction": "青海",
            },
            {
                "title": "青海生态环境监测专用设备 — 评分与参数扣分不匹配",
                "content": "青海省生态环境监测专用设备采购，参数满分45分，但△项119项×扣3分=357分，○项20项×1分=20分，扣分总额377分远超45分。处理结果：成立，中标无效。",
                "source": "青海政府采购网",
                "tags": "评分标准,参数扣分,不匹配,投诉成立",
                "jurisdiction": "青海",
            },
            # ── 四川典型案例 ──
            {
                "title": "四川成都 — 供应商变造检测报告参数",
                "content": "成都市某机械设备采购项目，供应商中标后被发现修改检测报告技术参数，谋取中标。处罚：罚款+列入黑名单+2年内禁止参与政府采购。",
                "source": "四川财政厅",
                "tags": "虚假材料,检测报告,行政处罚",
                "jurisdiction": "四川",
            },
            {
                "title": "四川教学实训中心 — 评审专家未按规定扣分",
                "content": "四川省某教学实训中心项目，供应商对技术参数做出负偏离响应，评审专家未按采购文件规定扣分。处罚：警告+罚款。",
                "source": "四川财政厅",
                "tags": "评审违规,参数扣分,行政处罚",
                "jurisdiction": "四川",
            },
            # ── 其他省 ──
            {
                "title": "甘肃食品安全监测平台 — 符合性审查程序错误",
                "content": "甘肃省食品安全风险监测信息化平台，评标委员会将非实质性条款缺失（产地信息未填写）错误认定为符合性审查不通过。处理结果：成立，中标无效，责令重新采购。",
                "source": "甘肃政府采购网",
                "tags": "程序违规,符合性审查,投诉成立",
                "jurisdiction": "甘肃",
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

        db.flush()

        # ── Phase 9: 案例节点 — 从 complaint_cases 表同步 (NEW) ──
        count += KnowledgeGraphService.sync_complaint_cases(db)

        db.flush()

        # ── Phase 10: 平台规则 → regulation 节点 — platform_rules.json ──
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

        db.flush()

        # ── Phase 11: 规则节点 — forbidden_words.json 禁用词模式 ──
        forbidden_words = KnowledgeGraphService._load_json(
            _RULES_DIR / "forbidden_words.json"
        )
        if forbidden_words:
            seen_forbidden_rule_ids = set()
            for category_key, patterns in forbidden_words.get("patterns", {}).items():
                if not isinstance(patterns, dict):
                    continue
                category_label = patterns.get("label", category_key)
                regex_list = patterns.get("regex_list", [])
                for item in regex_list:
                    pattern_id = item.get("id", "")
                    if not pattern_id:
                        continue
                    if pattern_id in seen_forbidden_rule_ids:
                        continue
                    seen_forbidden_rule_ids.add(pattern_id)
                    title = f"禁用词模式 {pattern_id}: {item.get('message', '')}"
                    if KnowledgeGraphService._node_exists_by_rule_id(db, pattern_id, "rule"):
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

        # ── Phase 12: 概念节点 — project_categories.json 项目分类 (NEW) ──
        # 使用 node_type="concept" 避免污染法规库
        proj_cat = KnowledgeGraphService._load_json(
            _RULES_DIR / "project_categories.json"
        )
        if proj_cat:
            # 导入分类组
            for cg in proj_cat.get("category_groups", []):
                cg_id = f"CAT-GROUP-{cg.get('id', '')}"
                if not KnowledgeGraphService._node_exists_by_rule_id(db, cg_id, "concept"):
                    n = KGNode(
                        node_type="concept",
                        title=f"项目分类组: {cg.get('name', '')}",
                        content=f"分类组: {cg.get('name', '')}\n"
                                f"图标: {cg.get('icon', '')}\n排序: {cg.get('order', '')}",
                        source="包合规项目分类体系",
                        tags="分类体系,项目分类,分类组",
                        rule_id=cg_id,
                        jurisdiction="全国",
                        trust_level=0.60,
                        audit_status="verified",
                    )
                    db.add(n)
                    count += 1
            # 导入子分类
            for cat in proj_cat.get("categories", []):
                cat_id = f"CAT-{cat.get('id', '')}"
                if not KnowledgeGraphService._node_exists_by_rule_id(db, cat_id, "concept"):
                    recommended = "推荐" if cat.get("recommended") else ""
                    n = KGNode(
                        node_type="concept",
                        title=f"项目分类: {cat.get('name', '')}",
                        content=f"分类: {cat.get('name', '')}\n"
                                f"父分类: {cat.get('parent', '')}\n"
                                f"图标: {cat.get('icon', '')}\n"
                                f"{'推荐分类' if recommended else '可选分类'}",
                        source="包合规项目分类体系",
                        tags=f"分类体系,项目分类,{cat.get('parent', '')},{recommended}".rstrip(","),
                        rule_id=cat_id,
                        jurisdiction="全国",
                        trust_level=0.60,
                        audit_status="verified",
                    )
                    db.add(n)
                    count += 1

        db.flush()

        # ═══════════════════════════════════════════════════════════════
        # Phase 13: 边创建 — 增强版
        # ═══════════════════════════════════════════════════════════════

        all_rules = db.query(KGNode).filter(KGNode.node_type == "rule").all()
        all_regulations = db.query(KGNode).filter(
            KGNode.node_type == "regulation"
        ).all()
        all_cases = db.query(KGNode).filter(KGNode.node_type == "case").all()
        edges_created = 0

        # 构建索引加速匹配
        reg_title_index = {}  # title → [reg_node, ...]
        for reg_node in all_regulations:
            if reg_node.title:
                t = reg_node.title
                reg_title_index.setdefault(t, []).append(reg_node)

        # ── edges A: rule → regulation (references) ──
        # 改进：检查法规标题、法规条文号（如"第二十条"）是否出现在规则内容中
        for rule_node in all_rules:
            for reg_node in all_regulations:
                if not reg_node.title or not rule_node.content:
                    continue
                matched = False
                # 完整标题匹配
                if len(reg_node.title) >= 8 and reg_node.title in rule_node.content:
                    matched = True
                # 标题前 10 字（处理缩写/简化）
                elif len(reg_node.title) >= 6 and reg_node.title[:10] in rule_node.content:
                    matched = True
                # 法规条文号匹配（如"第二十条"、"第三十二条"）
                elif _RE_ARTICLE_PAT.search(reg_node.content) and \
                     any(a in rule_node.content for a in _re.findall(r'第[一二三四五六七八九十百千]+条', reg_node.content)):
                    matched = True
                if matched:
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

        # ── edges B: rule → case (demonstrated_by) ──
        # 改进：标签交集 + 关键词匹配
        for rule_node in all_rules:
            rule_tags = set(t.strip().lower() for t in (rule_node.tags or "").split(","))
            rule_content_lower = (rule_node.content or "").lower()
            for case_node in all_cases:
                case_tags = set(t.strip().lower() for t in (case_node.tags or "").split(","))
                common_tags = rule_tags & case_tags
                # 排除仅因"规则"这通用标签匹配的
                meaningful = common_tags - {"规则", "rule", ""}
                if not meaningful:
                    continue
                # 至少需要 2 个共同标签，或者有特定关键词匹配
                if len(meaningful) >= 2 or \
                   any(kw in rule_content_lower for kw in meaningful):
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

        # ── edges C: case → regulation (cites) — 从案例的法律依据匹配法规 (NEW) ──
        for case_node in all_cases:
            case_content = (case_node.content or "").lower()
            for reg_node in all_regulations:
                if not reg_node.title:
                    continue
                reg_title_lower = reg_node.title.lower()
                # 案例内容包含法规标题
                if len(reg_node.title) >= 6 and reg_title_lower in case_content:
                    if not KnowledgeGraphService._edge_exists(
                        db, case_node.id, reg_node.id, "cites"
                    ):
                        e = KGEdge(
                            source_id=case_node.id,
                            target_id=reg_node.id,
                            relation="cites",
                            weight=0.8,
                        )
                        db.add(e)
                        edges_created += 1

        db.commit()
        logger.info(
            "知识图谱种子完成: %d 节点 + %d 边 (类型分布: reg=%d, rule=%d, case=%d)",
            count,
            edges_created,
            len(all_regulations),
            len(all_rules),
            len(all_cases),
        )
        return count + edges_created

    @staticmethod
    def sync_complaint_cases(db: Session) -> int:
        """将 `complaint_cases` 表同步为 KG case 节点。

        该方法是幂等的：
        - 已存在节点只更新基础展示字段，不会回写审核状态或可信度
        - 新节点默认 `audit_status='unreviewed'`、`trust_level=0.55`
        """
        decision_tag_map = {
            "upheld": "投诉成立",
            "rejected": "投诉驳回",
            "partial": "部分成立",
            "dismissed": "驳回",
        }

        def _parse_complaint_types(raw: str | None) -> list[str]:
            """将 complaint_types 字段解析为清洗后的标签列表。

            支持三种输入格式：
            1. 标准 JSON 数组：'["品牌锁定", "参数排他"]'
            2. Python repr 字符串（历史遗留）："['品牌锁定', '参数排他']" 或 "['O\\'Reilly', '品牌']"
            3. 空值/损坏值：返回空列表

            安全约束：优先 json.loads，失败后使用 ast.literal_eval 安全解析 Python 字面量。
            """
            if not raw or not raw.strip():
                return []
            raw = raw.strip()
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if item and str(item).strip()]
            except (json.JSONDecodeError, TypeError):
                pass
            # 历史 Python repr 兼容：使用 ast.literal_eval 安全解析
            # 相比手工引号替换，ast.literal_eval 正确处理撇号、转义、嵌套引号等边界情况
            if raw.startswith("[") and raw.endswith("]"):
                try:
                    parsed = ast.literal_eval(raw)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if item and str(item).strip()]
                except (ValueError, SyntaxError, TypeError):
                    pass
            # Fallback：无法解析时，作为单个标签处理
            cleaned = raw.strip("[]'\" \t\n\r")
            if cleaned:
                return [cleaned]
            return []

        synced = 0
        try:
            db_cases = db.query(ComplaintCase).filter(ComplaintCase.is_analyzed >= 0).all()
            for case in db_cases:
                cc_rule_id = f"CC-{case.id}"
                complaint_types = _parse_complaint_types(case.complaint_types)
                decision_label = decision_tag_map.get(case.decision_type, case.decision_type or "unknown")

                tags_parts = ["案例", "投诉案例", decision_label]
                tags_parts.extend(complaint_types)

                content_parts = []
                if case.project_name:
                    content_parts.append(f"项目名称: {case.project_name}")
                if case.project_number:
                    content_parts.append(f"项目编号: {case.project_number}")
                if case.decision_date:
                    content_parts.append(f"决定日期: {case.decision_date}")
                content_parts.append(f"处理结果: {decision_label}")
                if complaint_types:
                    content_parts.append(f"投诉类型: {', '.join(complaint_types)}")
                if case.legal_basis:
                    content_parts.append(f"法规依据: {case.legal_basis}")
                if case.summary:
                    content_parts.append(f"摘要: {case.summary}")

                title_prefix = f"[{case.province}] " if case.province and case.province != "全国" else ""
                title = f"{title_prefix}{case.title}"
                content = "\n".join(content_parts)[:2000]
                source = f"{case.province}政府采购网" if case.province else "政府采购网"
                source_url = case.source_url or ""
                tags = ",".join(filter(None, tags_parts))
                jurisdiction = case.province or ""
                publish_date = KnowledgeGraphService._parse_date(case.decision_date or "")
                metadata = {
                    "complaint_case_id": case.id,
                    "decision_type": case.decision_type,
                    "complaint_types": complaint_types,
                    "project_name": case.project_name,
                    "project_number": case.project_number,
                    "source_url": case.source_url,
                }

                existing = db.query(KGNode).filter(
                    KGNode.node_type == "case",
                    KGNode.rule_id == cc_rule_id,
                ).first()
                if existing:
                    changed = False
                    field_values = {
                        "title": title,
                        "content": content,
                        "source": source,
                        "source_url": source_url,
                        "tags": tags,
                        "jurisdiction": jurisdiction,
                        "publish_date": publish_date,
                        "metadata_json": json.dumps(metadata, ensure_ascii=False),
                    }
                    for field_name, value in field_values.items():
                        if getattr(existing, field_name) != value:
                            setattr(existing, field_name, value)
                            changed = True
                    if changed:
                        synced += 1
                    continue

                node = KGNode(
                    node_type="case",
                    title=title,
                    content=content,
                    source=source,
                    source_url=source_url,
                    tags=tags,
                    jurisdiction=jurisdiction,
                    rule_id=cc_rule_id,
                    publish_date=publish_date,
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                    trust_level=0.55,
                    audit_status="unreviewed",
                )
                db.add(node)
                synced += 1
        except Exception as e:
            logger.warning("从 complaint_cases 表同步案例节点失败: %s", e)
        finally:
            db.flush()

        return synced

    # ── 内部工具方法 ─────────────────────────────────

    @staticmethod
    def _node_exists(db: Session, title: str, node_type: str) -> bool:
        """检查节点是否已存在（幂等）"""
        return db.query(KGNode).filter(
            KGNode.title == title, KGNode.node_type == node_type
        ).first() is not None

    @staticmethod
    def _node_exists_by_rule_id(db: Session, rule_id: str, node_type: str = "rule") -> bool:
        """通过 rule_id + node_type 检查节点是否已存在（幂等）"""
        return db.query(KGNode).filter(
            KGNode.rule_id == rule_id, KGNode.node_type == node_type
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
        m = _re.match(r'[《「]([^》」]+)[》」]', law_ref)
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
        if not date_str:
            return None
        try:
            return date.fromisoformat(date_str)
        except (ValueError, TypeError):
            m = _re.match(r"(\d{4})-(\d{2})-(\d{2})", date_str)
            if m:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return None


# 预编译正则（模块级）
_RE_ARTICLE_PAT = _re.compile(r'第[一二三四五六七八九十百千]+条')

knowledge_graph = KnowledgeGraphService()
