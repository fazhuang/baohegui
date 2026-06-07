"""规则自动分析提炼 — 从已采集投诉案例中检测新违规模式"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.complaint_case import ComplaintCase

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

# ── 已知违规模式关键词 → 已有规则 ID 映射 ────────────────

KNOWN_PATTERN_TO_RULE = {
    "参数": "R007",
    "品牌": "R107",
    "指向": "R107",
    "排他": "R107",
    "授权": "R101",
    "检测报告": "R109",
    "厂家授权": "R101",
    "指定品牌": "R107",
    "歧视": "R101",
    "业绩": "R104",
    "认证": "R104-2",
    "进口": "R201",
    "中小企业": "AI-SME",
    "评分": "AI-SCORE-VAGUE",
    "评审": "AI-SCORE-VAGUE",
    "虚假": "R303",
    "串通": "R306",
    "资质": "R001",
    "混包": "F003",
    "低价": "F002",
    "标准": "E006",
    "★": "AI-COMBINE",
    "★参数": "AI-STAR-EXCESS",
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


def analyze_case(case: ComplaintCase, db: Session) -> dict:
    """分析单条案例，返回发现的模式"""
    text = (case.raw_content or "") + (case.summary or "")
    result = {
        "case_id": case.id,
        "title": case.title,
        "decision_type": case.decision_type,
        "found_patterns": [],
        "new_patterns": [],
        "summary": "",
    }

    if case.decision_type not in ("upheld", "partial"):
        return result  # 只分析投诉成立的案例

    # 1. 检测已知模式
    for kw, rule_id in KNOWN_PATTERN_TO_RULE.items():
        if kw in text:
            result["found_patterns"].append({"keyword": kw, "rule_id": rule_id})

    # 2. 检测新候选模式
    for name, cand in NEW_PATTERN_CANDIDATES.items():
        if re.search(cand["source_pattern"], text):
            # 检查这个模式对应的 rule_id 是否已经在已有规则中
            result["new_patterns"].append({
                "name": name,
                "rule_id": cand["rule_id"],
                "description": cand["description"],
                "suggestion": cand["suggestion"],
                "risk": cand["risk"],
                "is_new": cand["rule_id"] not in EXISTING_RULE_IDS,
            })

    # 3. 汇总
    if result["new_patterns"]:
        new_names = ", ".join(p["name"] for p in result["new_patterns"])
        result["summary"] = f"发现 {len(result['new_patterns'])} 种新模式: {new_names}"
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
        # 标记已分析
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
            "count": count,
            "rule_id": cand.get("rule_id", ""),
            "risk": cand.get("risk", "medium"),
            "is_new": cand.get("rule_id", "") not in EXISTING_RULE_IDS,
            "suggestion": cand.get("suggestion", ""),
        }
        if new_summary[name]["is_new"]:
            summary_parts.append(f"⚠️ 新候选模式「{name}」出现{count}次 → 建议新增规则 {cand.get('rule_id', '')}")

    return {
        "analyzed": total,
        "summary": "；".join(summary_parts),
        "known_patterns": dict(sorted(pattern_hits.items(), key=lambda x: -x[1])),
        "new_pattern_candidates": new_summary,
        "details": results,
    }
