"""案例去重服务

Phase 2 — 五层去重策略：
1. canonical_url — 权威 URL 精确匹配（强去重）
2. source_url — 源 URL 精确匹配（强去重）
3. content_hash — 内容 SHA256 精确匹配（强去重）
4. project_number / case_no — 项目/案件编号匹配（强去重）
5. 标题 + 内容相似度 — 仅作为候选建议，**不得静默删除**（弱去重）

强去重可自动标记 duplicate。
弱去重仅返回候选列表供人工审核决策。
"""

from __future__ import annotations

import hashlib
import json
import logging
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.complaint_case import ComplaintCase
from app.engine.case_state_machine import CaseStatus, CaseStatusStateMachine

logger = logging.getLogger(__name__)

# 相似度阈值（只做候选，不自动判定）
TITLE_SIMILARITY_THRESHOLD = 0.85
CONTENT_SIMILARITY_THRESHOLD = 0.80


class DedupService:
    """案例去重服务"""

    @staticmethod
    def compute_hash(content: str) -> str:
        """计算内容 SHA256"""
        if not content:
            return ""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def find_duplicates(
        db: Session,
        case: ComplaintCase,
        auto_mark: bool = True,
    ) -> dict:
        """查找重复案例，返回去重结果。

        auto_mark=True 时，强匹配自动标记 duplicate 并保存。
        返回：
        {
            "is_duplicate": bool,
            "method": str,           # 匹配方法
            "duplicates": [dict],    # 重复案例列表
            "candidates": [dict],    # 弱匹配候选（需人工判断）
            "auto_resolved": bool,   # 是否自动标记
        }
        """
        result = {
            "is_duplicate": False,
            "method": "",
            "duplicates": [],
            "candidates": [],
            "auto_resolved": False,
        }

        # ── 策略 1: canonical_url ──
        if case.canonical_url:
            dup = db.query(ComplaintCase).filter(
                ComplaintCase.canonical_url == case.canonical_url,
                ComplaintCase.id != case.id,
            ).first()
            if dup:
                result["is_duplicate"] = True
                result["method"] = "canonical_url"
                result["duplicates"].append(_dup_to_dict(dup))
                if auto_mark:
                    _auto_mark_duplicate(db, case, dup, "canonical_url")
                    result["auto_resolved"] = True
                return result

        # ── 策略 2: source_url ──
        if case.source_url:
            dup = db.query(ComplaintCase).filter(
                ComplaintCase.source_url == case.source_url,
                ComplaintCase.id != case.id,
            ).first()
            if dup:
                result["is_duplicate"] = True
                result["method"] = "source_url"
                result["duplicates"].append(_dup_to_dict(dup))
                if auto_mark:
                    _auto_mark_duplicate(db, case, dup, "source_url")
                    result["auto_resolved"] = True
                return result

        # ── 策略 3: content_hash ──
        if case.content_hash:
            dup = db.query(ComplaintCase).filter(
                ComplaintCase.content_hash == case.content_hash,
                ComplaintCase.id != case.id,
            ).first()
            if dup:
                result["is_duplicate"] = True
                result["method"] = "content_hash"
                result["duplicates"].append(_dup_to_dict(dup))
                if auto_mark:
                    _auto_mark_duplicate(db, case, dup, "content_hash")
                    result["auto_resolved"] = True
                return result

        # ── 策略 4: project_number / case_no ──
        if case.project_number or case.case_no:
            conditions = []
            if case.project_number:
                conditions.append(
                    ComplaintCase.project_number == case.project_number
                )
            if case.case_no:
                conditions.append(
                    ComplaintCase.case_no == case.case_no
                )
            existing = db.query(ComplaintCase).filter(
                or_(*conditions),
                ComplaintCase.id != case.id,
            ).all()
            if existing:
                result["is_duplicate"] = True
                result["method"] = "project_number/case_no"
                result["duplicates"] = [_dup_to_dict(d) for d in existing]
                if auto_mark:
                    for dup in existing:
                        _auto_mark_duplicate(db, case, dup, "project_number/case_no")
                    result["auto_resolved"] = True
                return result

        # ── 策略 5: 标题+内容相似度（仅候选，不静默标记）──
        same_source = db.query(ComplaintCase).filter(
            ComplaintCase.id != case.id,
        ).all()

        for existing in same_source:
            score = _compute_similarity(case, existing)
            if score["title"] >= TITLE_SIMILARITY_THRESHOLD or \
               score["content"] >= CONTENT_SIMILARITY_THRESHOLD:
                result["candidates"].append({
                    **_dup_to_dict(existing),
                    "title_similarity": round(score["title"], 3),
                    "content_similarity": round(score["content"], 3),
                })

        # 去重：排除已在 duplicates 中的
        dup_ids = {d["id"] for d in result["duplicates"]}
        result["candidates"] = [
            c for c in result["candidates"] if c["id"] not in dup_ids
        ]

        return result

    @staticmethod
    def check_before_save(
        db: Session,
        case: ComplaintCase,
    ) -> dict:
        """保存前检查去重 — 用于采集流程。

        与 find_duplicates 相同但更积极标记 duplicate。
        """
        # 自动计算 content_hash（如果没有）
        if not case.content_hash and (case.raw_content or case.summary):
            case.set_content_hash()

        return DedupService.find_duplicates(db, case, auto_mark=True)

    @staticmethod
    def bulk_dedup_check(
        db: Session,
        case_ids: Optional[list[int]] = None,
    ) -> dict:
        """批量去重检查。

        返回：
        {
            "total_checked": int,
            "strong_duplicates": int,    # 强匹配重复数
            "candidate_pairs": int,      # 弱匹配候选对数
            "details": [dict],
        }
        """
        query = db.query(ComplaintCase)
        if case_ids:
            query = query.filter(ComplaintCase.id.in_(case_ids))
        cases = query.all()

        details = []
        strong_count = 0
        candidate_count = 0

        seen_hashes = set()
        seen_urls = set()

        for case in cases:
            # content_hash check
            if case.content_hash:
                if case.content_hash in seen_hashes:
                    strong_count += 1
                    details.append({
                        "case_id": case.id,
                        "title": case.title,
                        "method": "content_hash",
                        "auto_resolved": True,
                    })
                    continue
                seen_hashes.add(case.content_hash)

            # source_url check
            if case.source_url:
                if case.source_url in seen_urls:
                    strong_count += 1
                    details.append({
                        "case_id": case.id,
                        "title": case.title,
                        "method": "source_url",
                        "auto_resolved": True,
                    })
                    continue
                seen_urls.add(case.source_url)

        return {
            "total_checked": len(cases),
            "strong_duplicates": strong_count,
            "candidate_pairs": candidate_count,
            "details": details,
        }


# ── 内部辅助 ────────────────────────────────────────

def _dup_to_dict(case: ComplaintCase) -> dict:
    """将重复案例转为简要 dict"""
    return {
        "id": case.id,
        "title": case.title,
        "source_url": case.source_url,
        "canonical_url": case.canonical_url,
        "project_number": case.project_number,
        "case_no": case.case_no,
        "decision_date": case.decision_date.isoformat() if case.decision_date else None,
        "review_status": case.review_status,
        "created_at": case.created_at.isoformat() if case.created_at else None,
    }


def _auto_mark_duplicate(
    db: Session,
    current: ComplaintCase,
    existing: ComplaintCase,
    method: str,
) -> None:
    """自动标记为重复（保留最早的一条）"""
    sm = CaseStatusStateMachine()

    # 保留先创建的，标记后创建的为 duplicate
    if current.created_at and existing.created_at:
        if current.created_at < existing.created_at:
            victim, survivor = existing, current
        else:
            victim, survivor = current, existing
    else:
        victim = current

    if victim.review_status not in (
        CaseStatus.PUBLISHED.value,
        CaseStatus.ARCHIVED.value,
    ):
        ok, msg = sm.transition(victim, CaseStatus.DUPLICATE.value)
        if ok:
            logger.info(f"案例 {victim.id} 自动标记为重复 (method={method})")
            db.commit()
        else:
            logger.warning(f"案例 {victim.id} 自动标记重复失败: {msg}")


def _compute_similarity(
    case1: ComplaintCase,
    case2: ComplaintCase,
) -> dict:
    """计算两个案例的相似度"""
    title1 = case1.title or ""
    title2 = case2.title or ""
    content1 = (case1.raw_content or "")[:5000]
    content2 = (case2.raw_content or "")[:5000]

    return {
        "title": SequenceMatcher(None, title1, title2).ratio(),
        "content": SequenceMatcher(None, content1, content2).ratio(),
    }


# 模块级单例
dedup_service = DedupService()
