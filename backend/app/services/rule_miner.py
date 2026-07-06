"""规则自动分析提炼 — 从已采集投诉案例中检测新违规模式

Phase 2 升级：
- 候选规则写入 candidate_rules 表（而非直接写入生产规则）
- 候选规则需通过人工审核（pending → approved → 正式规则资产）
- 不得直接热加载生产规则
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.complaint_case import ComplaintCase
from app.models.candidate_rule import CandidateRule

logger = logging.getLogger(__name__)

# ── 已有规则 ID 列表（用于去重判定是否为新模式） ──────────

EXISTING_RULE_IDS = {
    "R001", "R002", "R003", "R004", "R005", "R006", "R007", "R008",
    "R101", "R102", "R103", "R104", "R104-2", "R105", "R106", "R107", "R108", "R109", "R110", "R111",
    "R201", "R202", "R203", "R204", "R205", "R206", "R207",
    "R301", "R302", "R303", "R304", "R305", "R306", "R307", "R308",
    "R401", "R402", "R403", "R404", "R405", "R406", "R407", "R408",
    "R501", "R502", "R503", "R504", "R505",
    "R601", "R602", "R603", "R604", "R605", "R606", "R607",
    "R701", "R702", "R703", "R704", "R705",
    "E001", "E002", "E003", "E004", "E005", "E006", "E007",
    "F001", "F002", "F003",
}

KNOWN_PATTERN_TO_RULE = {
    "参数": "R007", "品牌": "R107", "指向": "R107", "排他": "R107",
    "授权": "R101", "检测报告": "R109", "厂家授权": "R101",
    "指定品牌": "R107", "歧视": "R101", "业绩": "R104",
    "认证": "R104-2", "进口": "R201", "中小企业": "AI-SME",
    "评分": "AI-SCORE-VAGUE", "评审": "AI-SCORE-VAGUE",
    "虚假": "R303", "串通": "R306", "资质": "R001",
    "混包": "F003", "低价": "F002", "标准": "E006",
    "★": "AI-COMBINE", "★参数": "AI-STAR-EXCESS",
    "辐射安全许可证": "E007",
}

NEW_PATTERN_CANDIDATES: dict[str, dict] = {
    "检测报告_注册证造假": {
        "rule_id": "AI-REG-VERIFY",
        "description": "供应商提供的检测报告/注册证号与药监局官网信息不符",
        "source_pattern": "检测报告|注册证|认证证书.*造假|虚假.*检测",
        "suggestion": "跨库验证：药监局数据库 vs 投标文件注册证信息",
        "risk": "critical",
    },
    "串通投标_MAC一致": {
        "rule_id": "AI-BID-RIGGING",
        "description": "多家供应商上传投标文件使用相同MAC地址、IP地址、CPU代码",
        "source_pattern": "MAC地址|IP地址.*相同|CPU代码|硬件特征码",
        "suggestion": "评标时检查电子投标文件的元数据特征信息",
        "risk": "critical",
    },
    "评审未按标准扣分": {
        "rule_id": "AI-EVAL-ERROR",
        "description": "评审专家未按采购文件要求对负偏离参数扣分",
        "source_pattern": "评审.*未.*扣分|未按.*标准.*评审|评审.*违规",
        "suggestion": "明确每项参数负偏离对应的扣分规则",
        "risk": "high",
    },
    "代理超标准收费": {
        "rule_id": "AI-FEE-EXCESS",
        "description": "代理机构实际收费超过招标代理服务费标准",
        "source_pattern": "代理.*费.*超标|多收.*服务费|超标准.*收费",
        "suggestion": "代理服务费对照《招标代理服务收费管理暂行办法》",
        "risk": "medium",
    },
    "符合性审查程序错误": {
        "rule_id": "AI-EVAL-ERROR",
        "description": "评标委员会将非实质性条款缺失认定为符合性审查不通过",
        "source_pattern": "符合性审查.*错误|非实质性.*条款.*无效",
        "suggestion": "区分实质性条款与非实质性条款的评审标准",
        "risk": "high",
    },
    "指定检测机构": {
        "rule_id": "FORB-L04",
        "description": "采购文件要求指定特定检测机构出具的检测报告",
        "source_pattern": "指定.*检测.*机构|特定.*检测.*报告|仅限.*检测",
        "suggestion": "改为具有CMA/CNAS资质的第三方检测机构",
        "risk": "medium",
    },
}


# ponytail: these are kept as module-level dicts, if rule count >500 switch to DB lookup


def analyze_case(case: ComplaintCase, db: Session) -> dict:
    """分析单条案例，返回发现的模式"""
    text = (case.raw_content or "") + (case.summary or "")
    result = {
        "case_id": case.id, "title": case.title,
        "decision_type": case.decision_type,
        "found_patterns": [], "new_patterns": [], "summary": "",
    }
    if case.decision_type not in ("upheld", "partial"):
        return result
    for kw, rule_id in KNOWN_PATTERN_TO_RULE.items():
        if kw in text:
            result["found_patterns"].append({"keyword": kw, "rule_id": rule_id})
    for name, cand in NEW_PATTERN_CANDIDATES.items():
        if re.search(cand["source_pattern"], text):
            result["new_patterns"].append({
                "name": name, "rule_id": cand["rule_id"],
                "description": cand["description"],
                "suggestion": cand["suggestion"], "risk": cand["risk"],
                "is_new": cand["rule_id"] not in EXISTING_RULE_IDS,
            })
    if result["new_patterns"]:
        result["summary"] = f"发现 {len(result['new_patterns'])} 种新模式"
    elif result["found_patterns"]:
        result["summary"] = f"匹配 {len(result['found_patterns'])} 个已知模式"
    else:
        result["summary"] = "未发现新违规模式"
    return result


def analyze_all_unanalyzed(db: Session) -> dict:
    """分析所有未分析的案例"""
    cases = db.query(ComplaintCase).filter(
        ComplaintCase.is_analyzed == 0,
        ComplaintCase.decision_type.in_(["upheld", "partial"]),
    ).all()
    results = []
    pattern_hits: dict[str, int] = {}
    new_pattern_hits: dict[str, int] = {}
    for case in cases:
        r = analyze_case(case, db)
        results.append(r)
        for fp in r["found_patterns"]:
            pattern_hits[fp["rule_id"]] = pattern_hits.get(fp["rule_id"], 0) + 1
        for np in r["new_patterns"]:
            new_pattern_hits[np["name"]] = new_pattern_hits.get(np["name"], 0) + 1
        case.is_analyzed = 1
    db.commit()
    total = len(cases)
    summary_parts = [f"分析 {total} 条成立/部分成立案例"]
    if pattern_hits:
        top = sorted(pattern_hits.items(), key=lambda x: -x[1])[:5]
        summary_parts.append(f"已知模式排行: {', '.join(f'{k}({v})' for k, v in top)}")
    new_summary = {}
    for name, count in sorted(new_pattern_hits.items(), key=lambda x: -x[1]):
        cand = NEW_PATTERN_CANDIDATES.get(name, {})
        new_summary[name] = {
            "count": count, "rule_id": cand.get("rule_id", ""),
            "risk": cand.get("risk", "medium"),
            "is_new": cand.get("rule_id", "") not in EXISTING_RULE_IDS,
            "suggestion": cand.get("suggestion", ""),
        }
        if new_summary[name]["is_new"]:
            summary_parts.append(f"⚠️ 新候选模式「{name}」出现{count}次 → 建议新增规则 {cand.get('rule_id', '')}")
    return {
        "analyzed": total, "summary": "；".join(summary_parts),
        "known_patterns": dict(sorted(pattern_hits.items(), key=lambda x: -x[1])),
        "new_pattern_candidates": new_summary, "details": results,
    }


# ═══════════════════════════════════════════════════════════════
# Phase 2: 候选规则写入（不直接写入生产规则）
# ═══════════════════════════════════════════════════════════════

MINER_VERSION = "2.0.0"


def mine_to_candidates(
    db: Session,
    case_ids: Optional[list[int]] = None,
    auto_write: bool = True,
) -> dict:
    """扫描案例并将新违规模式写入 candidate_rules 表。

    约束：
    - 只能创建 pending 状态候选规则
    - 只能更新 pending 状态候选规则的证据和置信度
    - rejected/duplicate/approved 候选规则不得被矿机再次修改
    - 不得直接写生产规则或触发规则热加载
    """
    q = db.query(ComplaintCase).filter(
        ComplaintCase.is_analyzed >= 0,
        ComplaintCase.decision_type.in_(["upheld", "partial"]),
    )
    if case_ids:
        q = q.filter(ComplaintCase.id.in_(case_ids))
    cases = q.all()

    created = 0
    updated = 0
    details = []

    for case in cases:
        analysis = analyze_case(case, db)
        if not analysis.get("new_patterns"):
            details.append({"case_id": case.id, "title": case.title, "new_patterns": 0})
            continue

        for pattern in analysis["new_patterns"]:
            candidate_id = f"CAND-{pattern['rule_id']}-{case.id}"
            existing = db.query(CandidateRule).filter(
                CandidateRule.candidate_id == candidate_id
            ).first()

            if existing:
                # 只能更新 pending 状态的候选规则
                if existing.review_status != "pending":
                    logger.info(
                        "跳过非 pending 候选规则: %s (status=%s)",
                        candidate_id, existing.review_status,
                    )
                    continue
                existing.evidence_snippets = _append_evidence(
                    existing.evidence_snippets, case, pattern,
                )
                existing.confidence = min(
                    1.0, (existing.confidence or 0.0) + 0.05,
                )
                existing.updated_at = datetime.now(timezone.utc)
                updated += 1
            elif auto_write:
                cand = CandidateRule(
                    candidate_id=candidate_id,
                    source_case_id=case.id,
                    source_type="miner",
                    rule_type="forbidden",
                    target=pattern.get("description", "")[:255],
                    description=pattern.get("description", ""),
                    risk_level=pattern.get("risk", "medium"),
                    category="candidate",
                    law_ref=_build_law_ref(case),
                    suggestion=pattern.get("suggestion", ""),
                    pattern=pattern.get("source_pattern", ""),
                    evidence_snippets=_build_evidence(case, pattern),
                    confidence=0.3,
                    miner_version=MINER_VERSION,
                    review_status="pending",
                )
                db.add(cand)
                created += 1

            details.append({
                "case_id": case.id, "title": case.title,
                "pattern": pattern["name"], "candidate_id": candidate_id,
                "rule_id": pattern["rule_id"], "risk": pattern.get("risk", "medium"),
            })

        case.is_analyzed = 2

    if auto_write and (created > 0 or updated > 0):
        db.commit()
        logger.info(
            f"候选规则挖掘完成: 扫描 {len(cases)} 条案例, "
            f"创建 {created} 条, 更新 {updated} 条候选规则"
        )

    return {
        "scanned": len(cases),
        "candidates_created": created,
        "candidates_updated": updated,
        "miner_version": MINER_VERSION,
        "details": details,
    }


def promote_candidate_to_rule(
    db: Session,
    candidate_id: int,
    reviewer_id: int,
    promoted_rule_id: str,
    note: str = "",
) -> dict:
    """将已审核通过的候选规则升级为正式规则资产（第二阶段的升级操作）。

    强制要求：
    - candidate 必须是 approved 状态
    - reviewed_by、reviewed_at 完整
    - 尚未 promoted
    - 不满足条件时拒绝创建 Rule，不修改 candidate
    - 不允许在一次调用中顺便把 pending 改成 approved
    """
    cand = db.query(CandidateRule).filter(CandidateRule.id == candidate_id).first()
    if not cand:
        return {"success": False, "error": "候选规则不存在"}

    if cand.review_status != "approved":
        return {
            "success": False,
            "error": f"候选规则必须先通过审核才能升级，当前状态: {cand.review_status}",
        }

    if not cand.reviewed_by or not cand.reviewed_at:
        return {
            "success": False,
            "error": "候选规则审核信息不完整（缺少 reviewed_by 或 reviewed_at），无法升级",
        }

    if cand.promoted_to:
        return {"success": False, "error": f"候选规则已升级为 {cand.promoted_to}，不可重复升级"}

    from app.models.rule import Rule

    existing = db.query(Rule).filter(Rule.rule_id == promoted_rule_id).first()
    if existing:
        return {"success": False, "error": f"正式规则 {promoted_rule_id} 已存在"}

    rule = Rule(
        rule_id=promoted_rule_id,
        rule_type=cand.rule_type,
        target=cand.target,
        description=cand.description,
        weight=5.0,
        category="mined",
        law_ref=cand.law_ref,
        suggestion=cand.suggestion,
        enabled=True,
        version="1.0",
    )
    db.add(rule)

    cand.mark_promoted(promoted_rule_id)
    db.commit()

    logger.info(f"候选规则 {cand.candidate_id} 升级为正式规则 {promoted_rule_id}")
    return {
        "success": True,
        "candidate_id": cand.candidate_id,
        "promoted_to": promoted_rule_id,
        "reviewed_by": reviewer_id,
    }


# ── Phase 2 辅助函数 ──────────────────────────────

def _build_evidence(case: ComplaintCase, pattern: dict) -> str:
    text = (case.raw_content or "") + (case.summary or "")
    source = pattern.get("source_pattern", "")
    snippets = []
    if source and text:
        for line in text.split("\n"):
            if re.search(source, line):
                snippets.append(line.strip()[:200])
                if len(snippets) >= 3:
                    break
    return json.dumps({
        "case_id": case.id, "title": case.title,
        "pattern": pattern["name"], "matches": snippets[:3],
    }, ensure_ascii=False)


def _append_evidence(existing_evidence: str | None, case: ComplaintCase, pattern: dict) -> str:
    existing = {}
    if existing_evidence:
        try:
            existing = json.loads(existing_evidence)
        except (json.JSONDecodeError, TypeError):
            existing = {}
    new_snippets = []
    text = (case.raw_content or "") + (case.summary or "")
    source = pattern.get("source_pattern", "")
    if source and text:
        for line in text.split("\n"):
            if re.search(source, line):
                new_snippets.append(line.strip()[:200])
                if len(new_snippets) >= 2:
                    break
    old_matches = existing.get("matches", [])
    existing["matches"] = (old_matches + new_snippets)[:10]
    existing["additional_cases"] = existing.get("additional_cases", [])
    if case.id not in [c.get("id") for c in existing["additional_cases"]]:
        existing["additional_cases"].append({"id": case.id, "title": case.title})
    return json.dumps(existing, ensure_ascii=False)


def _build_law_ref(case: ComplaintCase) -> str:
    if case.legal_basis:
        return case.legal_basis[:500]
    return ""
