"""双引擎结果融合

策略：
1. 规则引擎(60%) + 大模型引擎(40%) 加权评分
2. 智能去重：相同章节 + 文本相似度 ≥ threshold 视为重复，保留 LLM 的结果
3. 引擎内去重：同一引擎中同一章节+同一原文合并
4. 规则类型感知阈值：forbidden→exclusivity 用低阈值(0.25)，其他用高阈值(0.4)
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from .llm_engine import LLMEngineResult, LLMViolation
from .shared_types import RuleEngineResult, Violation

logger = logging.getLogger(__name__)


class ComplianceReport(BaseModel):
    """最终合规报告"""

    file_name: str = ""
    check_time: str = ""

    # 总评分
    total_score: float = 100.0

    # 分项评分
    section_score: float = 100.0
    keyword_score: float = 100.0
    forbidden_score: float = 100.0
    semantic_score: float = 100.0

    # 详细违规列表
    rule_violations: list[Violation] = []
    llm_violations: list[LLMViolation] = []

    # 统计
    total_violations: int = 0
    high_risk_count: int = 0
    medium_risk_count: int = 0
    low_risk_count: int = 0

    # 去重统计
    dedup_cross_engine: int = 0  # 跨引擎合并数
    dedup_intra_engine: int = 0  # 引擎内合并数

    # 审核信息
    llm_model_used: str = ""
    llm_tokens_used: int = 0
    llm_cost_yuan: float = 0.0
    llm_error: Optional[str] = None
    rule_count: int = 0


# ═══════════════════════════════════════════════════════════════
# 章节提取工具
# ═══════════════════════════════════════════════════════════════

_SECTION_RE = re.compile(r"《([^》]+)》")  # 《资格要求》
_LOCATION_RE = re.compile(r"^(.+?)[\s~:：]")  # 评审办法 ~第1行 / 资格要求：xxx
_SECTION_DESC_RE = re.compile(r"缺少《(.+?)》")  # 缺少《招标公告》章节
_SECTION_PLAIN_RE = re.compile(r"应在《(.+?)》中")  # 应在《评审办法》中


def _extract_section(text: str) -> str:
    """
    从违规的 location / description / text 中提取标准化章节名。
    按匹配精确度降序尝试多种模式。
    """
    if not text:
        return ""

    for pat in (_SECTION_RE, _SECTION_DESC_RE, _SECTION_PLAIN_RE, _LOCATION_RE):
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return ""


# ═══════════════════════════════════════════════════════════════
# 文本相似度 + 专名匹配
# ═══════════════════════════════════════════════════════════════

# 合规领域的同义短词映射（如"指定品牌"≈"指定使用XX品牌"）
_KNOWN_SYNONYM_PAIRS: list[tuple[str, str]] = [
    ("指定品牌", "指定"),
    ("唯一授权", "唯一"),
    ("指定型号", "指定"),
    ("本地注册", "本地"),
    ("注册资金", "注册"),
    ("本市注册", "本市"),
    ("地域限制", "限制"),
    ("独家", "独家"),
    ("必须", "必须"),
    ("倾向", "倾向"),
    ("仅限", "仅限"),
]


def _text_similarity(a: str, b: str, rule_type: str = "") -> float:
    """
    计算两段文本的语义相似度。

    使用三种策略并取最大值：
    1. 最长公共子串比例（通用）
    2. 合规专名词典匹配（如 "指定品牌" vs "指定使用XX品牌"）
    3. 短词完全匹配（如 "本地注册" == "本地注册企业" → 精确子串判定）

    Args:
        a: 文本 A
        b: 文本 B
        rule_type: 规则类型，用于调整判断标准

    Returns:
        相似度 0~1
    """
    if not a or not b:
        return 0.0

    a, b = (a.lower(), b.lower())
    shorter = a if len(a) <= len(b) else b
    longer = b if shorter is a else a

    # ── 策略 1：最长公共子串 ────────────────────────────────
    max_overlap = 0
    for i in range(len(shorter)):
        for j in range(i + 2, len(shorter) + 1):
            if shorter[i:j] in longer:
                max_overlap = max(max_overlap, j - i)
    lcs_score = max_overlap / max(len(shorter), 1)

    # ── 策略 2：合规专名词典匹配 ────────────────────────────
    term_score = 0.0
    for t1, t2 in _KNOWN_SYNONYM_PAIRS:
        if (t1 in a and t2 in b) or (t2 in a and t1 in b):
            term_score = max(term_score, 0.6)
        elif t1 in a and t1 in b:
            term_score = max(term_score, 0.8)

    return round(max(lcs_score, term_score), 3)


# ── 规则类型感知阈值 ─────────────────────────────────────────

_RULE_TYPE_PAIRS: dict[tuple[str, str], float] = {
    # (rule_engine_type, llm_type) → threshold
    ("forbidden", "exclusivity"): 0.25,
    ("forbidden", "hidden_barrier"): 0.25,
    ("forbidden", "bias"): 0.30,
    ("keyword_required", "exclusivity"): 0.40,
    ("keyword_required", "bias"): 0.40,
    ("chapter_required", "high_risk"): 0.50,
}


def _get_threshold(rv: Violation, lv: LLMViolation) -> float:
    """根据规则引擎和 LLM 的违规类型获取合适的去重阈值"""
    key = (rv.rule_type, lv.type)
    return _RULE_TYPE_PAIRS.get(key, 0.35)  # 默认 0.35


# ═══════════════════════════════════════════════════════════════
# 引擎内去重
# ═══════════════════════════════════════════════════════════════


def _dedup_intra_engine(
    violations: list[Violation],
) -> tuple[list[Violation], int]:
    """
    同一引擎内去重：相同章节 + 相同原文 + 相同风险等级 → 只保留第一条。

    Returns:
        (deduped_list, removed_count)
    """
    if len(violations) <= 1:
        return violations, 0

    seen: set[tuple[str, str, str]] = set()
    result: list[Violation] = []
    removed = 0

    for v in violations:
        sec = _extract_section(v.location or v.description)
        txt = v.text or v.description
        key = (sec, txt, v.risk_level)
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        result.append(v)

    return result, removed


# ═══════════════════════════════════════════════════════════════
# 融合引擎
# ═══════════════════════════════════════════════════════════════


class FusionEngine:
    """融合规则引擎和大模型引擎的结果"""

    @staticmethod
    def deduplicate(
        rule_violations: list[Violation],
        llm_violations: list[LLMViolation],
    ) -> tuple[list[Violation], list[LLMViolation]]:
        """
        双引擎结果去重。

        策略（规则引擎优先）：
        - 如果 LLM 违规与某条规则违规满足"同章节 + 同风险等级 + LLM 原文是规则原文的子串"，
          则视为重复 → 以规则引擎为准（保留规则，剔除 LLM）
        - 如果 LLM 发现的是规则引擎未覆盖的新违规 → 保留 LLM 条目

        Args:
            rule_violations: 规则引擎原始违规列表
            llm_violations:  LLM 引擎原始违规列表

        Returns:
            (kept_rule_violations, kept_llm_violations)
            rule_violations 原样返回（不做引擎内去重），
            llm_violations 中与规则引擎重复的被移除。
        """
        if not rule_violations or not llm_violations:
            return rule_violations, llm_violations

        keep_llm = [True] * len(llm_violations)

        for i, lv in enumerate(llm_violations):
            l_section = lv.section or _extract_section(lv.text)
            l_text = lv.text or ""

            for rv in rule_violations:
                r_section = _extract_section(rv.location or rv.description)
                r_text = rv.text or rv.description

                # ── 条件 1：同章节 ──────────────────────────
                # 两个章节名都必须非空，且相等
                if not r_section or not l_section:
                    continue
                if r_section != l_section:
                    continue

                # ── 条件 2：同风险等级 ──────────────────────
                if rv.risk_level != lv.risk_level:
                    continue

                # ── 条件 3：LLM 原文 ⊆ 规则原文（子串包含）─
                if not l_text or l_text not in r_text:
                    continue

                # 全部满足 → 视为重复，剔除 LLM 条目
                keep_llm[i] = False
                logger.debug(
                    "去重合并: 规则=%s(%s, %s) ≈ LLM=%s(%s, %s) → 保留规则",
                    rv.rule_id,
                    r_section,
                    rv.risk_level,
                    lv.type,
                    l_section,
                    lv.risk_level,
                )
                break  # 一条 LLM 违规至多匹配一条规则

        llm_kept = [v for i, v in enumerate(llm_violations) if keep_llm[i]]
        return rule_violations, llm_kept

    @staticmethod
    def _risk_penalty(risk_level: str, weight: float = 10.0) -> float:
        """
        根据风险等级计算单条违规的扣分。

        风险等级基础扣分（可叠加 weight 缩放）：
          high   → 10 分（范围 8-15，weight≥20 时取 15，weight≥10 时取 10，其他取 8）
          medium →  5 分（范围 3-7，weight≥15 时取 7，weight≥5 时取 5，其他取 3）
          low    →  1 分（范围 1-2，weight≥10 时取 2，其他取 1）
        """
        if risk_level == "high":
            if weight >= 20:
                return 15.0
            elif weight >= 10:
                return 10.0
            return 8.0
        elif risk_level == "medium":
            if weight >= 15:
                return 7.0
            elif weight >= 5:
                return 5.0
            return 3.0
        else:  # low
            return 2.0 if weight >= 10 else 1.0

    @staticmethod
    def calculate_total_score(
        rule_result: RuleEngineResult,
        llm_result: Optional[LLMEngineResult] = None,
    ) -> dict:
        """
        根据去重后的违规列表计算综合评分。

        评分权重：
        - 规则引擎 60% + LLM 40%（LLM 可用时）
        - 仅规则引擎时：100%

        惩罚规则（基于违规的风险等级和 weight）：
        - 高风险：每条 8-15 分（默认 10）
        - 中风险：每条 3-7 分（默认 5）
        - 低风险：每条 1-2 分（默认 1）

        Returns:
            {
                "total_score": float,
                "rule_penalty": float,
                "llm_penalty": float,
                "rule_raw_score": float,
                "llm_raw_score": float,
            }
        """
        has_llm = llm_result is not None and len(llm_result.violations) > 0

        # 规则引擎融合层同样使用阶梯衰减计算惩罚分
        import math

        # 按 risk_level 排序（high > medium > low），再按 weight 降序
        _risk_order = {"high": 0, "medium": 1, "low": 2}
        sorted_v = sorted(
            rule_result.violations, key=lambda v: (_risk_order.get(v.risk_level, 2), -v.weight)
        )
        rule_penalty = sum(
            FusionEngine._risk_penalty(v.risk_level, v.weight) / math.sqrt(i + 1)
            for i, v in enumerate(sorted_v)
        )

        # 计算 LLM 引擎惩罚（LLM 违规数量通常较少，用线性衰减）
        if has_llm:
            llm_penalty = sum(
                FusionEngine._risk_penalty(v.risk_level, v.weight) for v in llm_result.violations
            )
        else:
            llm_penalty = 0.0

        # 加权融合
        if has_llm:
            weighted_penalty = rule_penalty * 0.6 + llm_penalty * 0.4
        else:
            weighted_penalty = rule_penalty

        total_score = round(max(0.0, min(100.0, 100.0 - weighted_penalty)), 1)

        rule_raw = round(max(0.0, 100.0 - rule_penalty), 1)
        llm_raw = round(max(0.0, 100.0 - llm_penalty), 1) if has_llm else 100.0

        return {
            "total_score": total_score,
            "rule_penalty": round(rule_penalty, 1),
            "llm_penalty": round(llm_penalty, 1),
            "rule_raw_score": rule_raw,
            "llm_raw_score": llm_raw,
        }

    @staticmethod
    def merge(
        rule_result: RuleEngineResult,
        llm_result: Optional[LLMEngineResult] = None,
        file_name: str = "",
        check_time: str = "",
    ) -> ComplianceReport:
        """合并两个引擎的结果，去重并计算综合评分"""

        rule_violations = rule_result.violations
        llm_violations = llm_result.violations if llm_result else []

        # ── 去重：规则引擎优先 ──────────────────────────────
        rule_final, llm_final = FusionEngine.deduplicate(
            rule_violations,
            llm_violations,
        )
        merged_count = len(llm_violations) - len(llm_final)

        # ── 统计风险等级（去重后） ──────────────────────────
        all_violations = list(rule_final) + list(llm_final)
        high_risk = sum(1 for v in all_violations if getattr(v, "risk_level", "low") == "high")
        medium_risk = sum(1 for v in all_violations if getattr(v, "risk_level", "low") == "medium")
        low_risk = sum(1 for v in all_violations if getattr(v, "risk_level", "low") == "low")

        # ── 综合评分（基于去重后的违规列表 + 加权融合） ──────
        # 用去重后的违规列表计算，避免重复计分
        deduped_rule_for_scoring = RuleEngineResult(
            violations=rule_final,
            section_score=rule_result.section_score,
            keyword_score=rule_result.keyword_score,
            forbidden_score=rule_result.forbidden_score,
            total_score=rule_result.total_score,
        )
        score_info = FusionEngine.calculate_total_score(deduped_rule_for_scoring, llm_result)
        combined_total = score_info["total_score"]

        logger.info(
            "融合完成: 规则%d→%d LLM%d 去重%d 规则惩罚%.1f LLM惩罚%.1f 总分%.1f",
            len(rule_violations),
            len(rule_final),
            len(llm_final),
            merged_count,
            score_info["rule_penalty"],
            score_info["llm_penalty"],
            combined_total,
        )

        return ComplianceReport(
            file_name=file_name,
            check_time=check_time,
            total_score=combined_total,
            section_score=round(rule_result.section_score, 1),
            keyword_score=round(rule_result.keyword_score, 1),
            forbidden_score=round(rule_result.forbidden_score, 1),
            semantic_score=round(score_info["llm_raw_score"], 1),
            rule_violations=rule_final,
            llm_violations=llm_final,
            total_violations=len(all_violations),
            high_risk_count=high_risk,
            medium_risk_count=medium_risk,
            low_risk_count=low_risk,
            dedup_cross_engine=merged_count,
            dedup_intra_engine=0,
            llm_model_used=llm_result.model_used if llm_result else "",
            llm_tokens_used=llm_result.tokens_used if llm_result else 0,
            llm_cost_yuan=llm_result.cost_yuan if llm_result else 0.0,
            llm_error=llm_result.error if llm_result else None,
            rule_count=len(rule_violations),
        )


fusion_engine = FusionEngine()


# ═══════════════════════════════════════════════════════════════
# 四路风险合并器 + 复核状态机
# ═══════════════════════════════════════════════════════════════

from app.engine.shared_types import (
    BiasFinding,
    ParameterBiasResult,
    RoutingResult,
    TrafficLight,
)


class MergedRiskItem(BaseModel):
    """单条合并后的风险项"""
    source: str = Field(..., description="rule / bias / llm")
    risk_level: str = Field(..., pattern=r"^(critical|high|medium|low)$")
    category: str = Field(
        ...,
        pattern=r"^(confirmed|high_risk|needs_review|advisory)$",
    )
    title: str = ""
    description: str = ""
    evidence_text: str = ""
    suggestion: str = ""
    law_ref: Optional[str] = None
    confidence: float = 0.0


class MergeResult(BaseModel):
    """四路风险合并结果"""
    final_passed: bool = True
    risk_level: str = Field(default="low", pattern=r"^(low|medium|high|critical)$")
    risk_level_original: str = Field(default="low")
    review_status: str = Field(
        default="auto_passed",
        pattern=r"^(auto_passed|auto_failed|needs_review|reviewed_passed|reviewed_failed)$",
    )
    requires_human_review: bool = False
    risk_items: list[MergedRiskItem] = []
    confirmed_count: int = 0
    high_risk_count: int = 0
    needs_review_count: int = 0
    advisory_count: int = 0
    parse_quality_adjustment: str = "none"  # none / upgraded / downgraded
    routing_used: bool = False


class FourWayRiskMerger:
    """四路风险合并器 —— 合并路由、规则、参数倾向性、LLM四路结果"""

    def merge(
        self,
        routing_result: Optional[RoutingResult] = None,
        rule_engine_result: Optional[RuleEngineResult] = None,
        parameter_bias_result: Optional[ParameterBiasResult] = None,
        llm_result: Optional[LLMEngineResult] = None,
        parse_quality: str = "ok",
    ) -> MergeResult:
        """
        合并四路审查结果，输出统一的风险评估。

        合并策略：
        - confirmed：规则引擎 forbidden_pattern 命中 + 参数倾向性交叉确认
        - high_risk：规则命中但未被参数倾向性确认，或参数倾向性高分
        - needs_review：低置信度发现，需人工判断
        - advisory：轻微风险提示

        Returns:
            MergeResult with final assessment
        """
        risk_items: list[MergedRiskItem] = []

        # ── 从各层提取结果 ──────────────────────────────────
        rule_violations = rule_engine_result.violations if rule_engine_result else []
        bias_findings = parameter_bias_result.findings if parameter_bias_result else []
        llm_violations = llm_result.violations if llm_result else []

        # 构建规则ID和参数模式ID集合用于交叉验证
        rule_ids = {v.rule_id for v in rule_violations if v.rule_id}
        bias_rule_ids = {f.rule_id for f in bias_findings if f.rule_id}

        # ── 从规则引擎提取风险 ──────────────────────────────
        for v in rule_violations:
            is_forbidden = v.rule_type == "forbidden"
            confirmed_by_bias = v.rule_id in bias_rule_ids

            if is_forbidden and confirmed_by_bias:
                category = "confirmed"
            elif is_forbidden or v.risk_level == "high":
                category = "high_risk"
            elif v.risk_level == "medium":
                category = "needs_review"
            else:
                category = "advisory"

            risk_items.append(MergedRiskItem(
                source="rule",
                risk_level=v.risk_level,
                category=category,
                title=f"[{v.rule_id}] {v.description[:80]}",
                description=v.description,
                evidence_text=v.text or "",
                suggestion=v.suggestion,
                law_ref=v.law_ref,
                confidence=0.95 if category == "confirmed" else 0.80,
            ))

        # ── 从参数倾向性提取风险（不与规则重复的）───────────
        for f in bias_findings:
            if f.rule_id and f.rule_id in rule_ids:
                continue  # 规则引擎已覆盖，只做交叉确认不重复报告
            category = "high_risk" if f.severity in ("critical", "high") else "needs_review"
            risk_items.append(MergedRiskItem(
                source="bias",
                risk_level="high" if f.severity == "critical" else f.severity,
                category=category,
                title=f"[{f.pattern_id}] {f.pattern_name}",
                description=f.description,
                evidence_text=f.matched_text,
                suggestion=f.suggestion or "",
                law_ref=f.law_ref,
                confidence=f.confidence,
            ))

        # ── 从LLM提取风险（默认需人工确认）───────────────────
        for lv in llm_violations:
            category = "needs_review"
            if lv.risk_level == "high":
                category = "high_risk"
            risk_items.append(MergedRiskItem(
                source="llm",
                risk_level=lv.risk_level,
                category=category,
                title=f"[{lv.type}] {lv.reason[:80]}" if lv.reason else f"[{lv.type}] LLM检测风险",
                description=lv.reason,
                evidence_text=lv.text,
                suggestion=lv.suggestion,
                law_ref=lv.law_ref,
                confidence=0.65,
            ))

        # ── 解析质量调整 ─────────────────────────────────────
        quality_multiplier = {"ok": 1.0, "text_layer": 1.0, "ocr": 1.2, "partial": 1.5, "failed": 2.0}
        adjustment = "none"
        if parse_quality in ("ocr", "partial", "failed"):
            adjustment = "upgraded"

        # ── 计数统计 ──────────────────────────────────────────
        confirmed_count = sum(1 for r in risk_items if r.category == "confirmed")
        high_risk_count = sum(1 for r in risk_items if r.category == "high_risk")
        needs_review_count = sum(1 for r in risk_items if r.category == "needs_review")
        advisory_count = sum(1 for r in risk_items if r.category == "advisory")

        # ── 综合判定风险等级 ──────────────────────────────────
        if confirmed_count > 0:
            risk_level = "critical" if confirmed_count >= 2 else "high"
        elif high_risk_count > 0:
            risk_level = "high"
        elif needs_review_count > 0:
            risk_level = "medium"
        else:
            risk_level = "low"

        risk_level_original = risk_level

        # 解析质量差时上调风险等级
        if adjustment == "upgraded":
            if risk_level == "low":
                risk_level = "medium"
            elif risk_level == "medium":
                risk_level = "high"

        # ── 判定是否通过 ──────────────────────────────────────
        final_passed = confirmed_count == 0 and high_risk_count == 0

        # ── 复核状态机 ────────────────────────────────────────
        if final_passed and needs_review_count == 0:
            review_status = "auto_passed"
            requires_human_review = False
        elif confirmed_count > 0:
            review_status = "auto_failed"
            requires_human_review = True
        else:
            review_status = "needs_review"
            requires_human_review = True

        logger.info(
            "四路合并: passed=%s level=%s status=%s confirmed=%d high=%d review=%d advisory=%d",
            final_passed, risk_level, review_status,
            confirmed_count, high_risk_count, needs_review_count, advisory_count,
        )

        return MergeResult(
            final_passed=final_passed,
            risk_level=risk_level,
            risk_level_original=risk_level_original,
            review_status=review_status,
            requires_human_review=requires_human_review,
            risk_items=risk_items,
            confirmed_count=confirmed_count,
            high_risk_count=high_risk_count,
            needs_review_count=needs_review_count,
            advisory_count=advisory_count,
            parse_quality_adjustment=adjustment,
            routing_used=routing_result is not None,
        )


# ── 全局单例 ──────────────────────────────────────────────────
four_way_merger = FourWayRiskMerger()
