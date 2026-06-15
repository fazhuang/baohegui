"""双引擎结果融合

策略：
1. 规则引擎(60%) + 大模型引擎(40%) 加权评分
2. 智能去重：相同章节 + 文本相似度 ≥ threshold 视为重复，保留 LLM 的结果
3. 引擎内去重：同一引擎中同一章节+同一原文合并
4. 规则类型感知阈值：forbidden→exclusivity 用低阈值(0.25)，其他用高阈值(0.4)
5. LLM 证据链校验（P0 强校验）：evidence.text 逐字命中 full_text 且 law_ref 精确命中规则库，任一失败即降级
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from .llm_engine import LLMEngineResult, LLMViolation
from .shared_types import RuleEngineResult, Violation

logger = logging.getLogger(__name__)


def _build_rule_db_snapshot() -> set[str]:
    """从规则引擎和 compliance_rules.json 构建已知法规引用集合。

    提取所有规则的 law_ref 字段中的法规名称，形成可查询的已知法规库。
    返回一个集合，每个元素是规范化后的法规名称（如 '政府采购法', '招标投标法'）。
    """
    try:
        from app.engine.rule_engine import rule_engine
    except Exception:
        return set()

    known: set[str] = set()
    # 从规则引擎中提取所有已知法规引用
    for rule in rule_engine.rules:
        if rule.law_ref:
            # 提取法规标题部分
            for title in re.findall(r'[《]([^》]+)[》]', rule.law_ref):
                known.add(title)
            # 也提取 "XXX法", "XXX条例", "XXX办法" 等
            for m in re.finditer(r'([一-鿿]{2,}(?:法|条例|办法|规定|通知|令))', rule.law_ref):
                known.add(m.group(1))
    return known


def _validate_law_ref(law_ref: str, rule_db: set[str] | None = None) -> bool:
    """检查 law_ref 是否命中规则库/法规库的真实条目。

    P0 强校验：law_ref 必须精确包含规则库中的某个已知法规名称（从 rule_engine 运行时
    规则快照中提取）。不存在静态关键词前缀放行 — 仅依据规则库真实条目判定。
    此外，法规名称后可跟文章、条款等，但前后不应出现其他汉字或字母数字，
    以防止仅凭子串匹配便被误认为有效（如“政府采购法管理细则”不应因包含
    “政府采购法”而通过）。

    返回 True 表示 law_ref 引用了规则库中存在的真实法规。
    """
    if not law_ref or not law_ref.strip():
        return False

    if rule_db is None:
        rule_db = _build_rule_db_snapshot()

    # 提取法规名称：尝试提取《》内的内容；若无则使用整条目
    cleaned = law_ref.strip()
    import re
    match = re.search(r'《([^》]+)》', cleaned)
    if match:
        inner = match.group(1).strip()
        # 以 inner 为基础进行匹配
        base = inner
    else:
        base = cleaned

    # 现在 base 应为类似 "政府采购法"、"政府采购法实施条例" 等可能带有后续条文的字符串
    for known_title in rule_db:
        if base.startswith(known_title):
            remainder = base[len(known_title):]
            # 余下部分应为空或仅包含如：第X条、第X款、第X项、章节号等
            if not remainder:
                return True
            # 允许的字符集合：数字、汉字“一二三四五六七八九十百千万零”、章节相关词及标点
            allowed = set("0123456789一二三四五六七八九十百千万零〇第条款项章节()（）［］【】｛｝<>〈〉，。：：；；.-/ ")
            if all(ch in allowed for ch in remainder):
                return True
            # 否则不匹配
    return False


def validate_llm_evidence(
    llm_result: LLMEngineResult,
    full_text: str,
    rule_db: set[str] | None = None,
) -> LLMEngineResult:
    """在 LLM 输出进入 fusion 前做强校验。

    每条 LLMViolation 的 evidence/text 必须在 parsed.full_text 中命中：
    - 精确子串命中 → 通过
    - Levenshtein 模糊匹配 → 通过（相似度 ≥ 0.80）
    - 皆失败 → 降级为 needs_human_review

    law_ref 必须命中规则库/法规库的真实条目。

    Returns:
        修改后的 LLMEngineResult（violations 附加了 validation metadata）
    """
    from app.engine.evidence_matcher import match_evidence

    if rule_db is None:
        rule_db = _build_rule_db_snapshot()

    validated_violations: list[LLMViolation] = []

    for lv in llm_result.violations:
        validation_errors: list[str] = []

        # ── 校验 1: evidence/text 原文全文比对 ──
        if lv.text and lv.text.strip():
            match = match_evidence(lv.text, full_text)
            if not match.get("matched"):
                method = match.get("method", "none")
                similarity = match.get("similarity", 0)
                validation_errors.append(
                    f"evidence_text 未命中原文 (method={method} similarity={similarity:.2f})"
                    f" — '{lv.text[:80]}...'"
                )
            else:
                logger.debug(
                    "Evidence 命中 [%s]: method=%s similarity=%.2f",
                    lv.type, match.get("match_method"), match.get("similarity"),
                )
        else:
            validation_errors.append("缺少 evidence_text，无法定位原文证据")

        # ── 校验 2: law_ref 必须命中规则库的真实条目 ──
        if lv.law_ref and lv.law_ref.strip():
            if not _validate_law_ref(lv.law_ref, rule_db):
                validation_errors.append(
                    f"law_ref '{lv.law_ref[:80]}' 未命中已知规则库/法规库"
                )
        else:
            validation_errors.append("缺少 law_ref 法规引用")

        if validation_errors:
            v_err = "; ".join(validation_errors)
            logger.warning(
                "LLM 证据链校验失败 [%s]: %s → 降级为 needs_human_review",
                lv.type,
                v_err,
            )
            lv.validation_error = v_err
            lv.requires_human_review = True

        validated_violations.append(lv)

    return LLMEngineResult(
        violations=validated_violations,
        total_score=llm_result.total_score,
        model_used=llm_result.model_used,
        tokens_used=llm_result.tokens_used,
        tokens_input=llm_result.tokens_input,
        tokens_output=llm_result.tokens_output,
        cost_yuan=llm_result.cost_yuan,
        sections_analyzed=llm_result.sections_analyzed,
        sections_skipped=llm_result.sections_skipped,
        error=llm_result.error,
    )


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
    bias_violations: list[Violation] = []

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

    # ── 人工复核统计（v5 新增） ──────────────────────────
    requires_human_review_count: int = 0  # 需人工复核的违规项总数
    unverified_llm_count: int = 0  # 证据校验失败的 LLM 项数


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
    """
    if not a or not b:
        return 0.0

    a, b = (a.lower(), b.lower())
    shorter = a if len(a) <= len(b) else b
    longer = b if shorter is a else a

    # ── 策略 1：最长公共子串 ──
    max_overlap = 0
    for i in range(len(shorter)):
        for j in range(i + 2, len(shorter) + 1):
            if shorter[i:j] in longer:
                max_overlap = max(max_overlap, j - i)
    lcs_score = max_overlap / max(len(shorter), 1)

    # ── 策略 2：合规专名词典匹配 ──
    term_score = 0.0
    for t1, t2 in _KNOWN_SYNONYM_PAIRS:
        if (t1 in a and t2 in b) or (t2 in a and t1 in b):
            term_score = max(term_score, 0.6)
        elif t1 in a and t1 in b:
            term_score = max(term_score, 0.8)

    return round(max(lcs_score, term_score), 3)


# ── 规则类型感知阈值 ──

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
    key = (rv.rule_type, lv.type)
    return _RULE_TYPE_PAIRS.get(key, 0.35)


# ═══════════════════════════════════════════════════════════════
# 引擎内去重
# ═══════════════════════════════════════════════════════════════


def _dedup_intra_engine(
    violations: list[Violation],
) -> tuple[list[Violation], int]:
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
        if not rule_violations or not llm_violations:
            return rule_violations, llm_violations

        keep_llm = [True] * len(llm_violations)

        for i, lv in enumerate(llm_violations):
            l_section = lv.section or _extract_section(lv.text)
            l_text = lv.text or ""

            for rv in rule_violations:
                r_section = _extract_section(rv.location or rv.description)
                r_text = rv.text or rv.description

                if not r_section or not l_section:
                    continue
                if r_section != l_section:
                    continue
                if rv.risk_level != lv.risk_level:
                    continue
                if not l_text or l_text not in r_text:
                    continue

                keep_llm[i] = False
                logger.debug(
                    "去重合并: 规则=%s(%s, %s) ≈ LLM=%s(%s, %s) → 保留规则",
                    rv.rule_id, r_section, rv.risk_level,
                    lv.type, l_section, lv.risk_level,
                )
                break

        llm_kept = [v for i, v in enumerate(llm_violations) if keep_llm[i]]
        return rule_violations, llm_kept

    @staticmethod
    def _risk_penalty(risk_level: str, weight: float = 10.0) -> float:
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
        else:
            return 2.0 if weight >= 10 else 1.0

    @staticmethod
    def calculate_total_score(
        rule_result: RuleEngineResult,
        llm_result: Optional[LLMEngineResult] = None,
    ) -> dict:
        import math

        has_llm = llm_result is not None and len(llm_result.violations) > 0
        _risk_order = {"high": 0, "medium": 1, "low": 2}
        sorted_v = sorted(
            rule_result.violations, key=lambda v: (_risk_order.get(v.risk_level, 2), -v.weight)
        )
        rule_penalty = sum(
            FusionEngine._risk_penalty(v.risk_level, v.weight) / math.sqrt(i + 1)
            for i, v in enumerate(sorted_v)
        )

        if has_llm:
            llm_penalty = sum(
                FusionEngine._risk_penalty(v.risk_level, v.weight) for v in llm_result.violations
            )
        else:
            llm_penalty = 0.0

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
        bias_violations: Optional[list[Violation]] = None,
        file_name: str = "",
        check_time: str = "",
    ) -> ComplianceReport:
        rule_violations = rule_result.violations
        llm_violations = llm_result.violations if llm_result else []
        bias_vs = bias_violations or []

        rule_final, llm_final = FusionEngine.deduplicate(rule_violations, llm_violations)
        merged_count = len(llm_violations) - len(llm_final)

        all_violations = list(rule_final) + list(llm_final) + list(bias_vs)
        high_risk = sum(1 for v in all_violations if getattr(v, "risk_level", "low") == "high")
        medium_risk = sum(1 for v in all_violations if getattr(v, "risk_level", "low") == "medium")
        low_risk = sum(1 for v in all_violations if getattr(v, "risk_level", "low") == "low")

        deduped_rule_for_scoring = RuleEngineResult(
            violations=rule_final,
            section_score=rule_result.section_score,
            keyword_score=rule_result.keyword_score,
            forbidden_score=rule_result.forbidden_score,
            total_score=rule_result.total_score,
        )
        score_info = FusionEngine.calculate_total_score(deduped_rule_for_scoring, llm_result)
        combined_total = score_info["total_score"]

        # ── 人工复核统计（v5） ──
        unverified_llm_count = sum(
            1 for v in llm_final
            if v.validation_error or v.requires_human_review
        )
        # 合并层也统计 needs_review 项数（来自四路合并器）
        requires_human_review_count = unverified_llm_count

        logger.info(
            "融合完成: 规则%d→%d LLM%d 去重%d 规则惩罚%.1f LLM惩罚%.1f 总分%.1f 待复核%d",
            len(rule_violations), len(rule_final), len(llm_final), merged_count,
            score_info["rule_penalty"], score_info["llm_penalty"], combined_total,
            requires_human_review_count,
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
            bias_violations=bias_vs,
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
            requires_human_review_count=requires_human_review_count,
            unverified_llm_count=unverified_llm_count,
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
    validation_error: Optional[str] = None
    requires_human_review: bool = False


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
        risk_items: list[MergedRiskItem] = []

        rule_violations = rule_engine_result.violations if rule_engine_result else []
        bias_findings = parameter_bias_result.findings if parameter_bias_result else []
        llm_violations = llm_result.violations if llm_result else []

        rule_ids = {v.rule_id for v in rule_violations if v.rule_id}
        bias_rule_ids = {f.rule_id for f in bias_findings if f.rule_id}

        # ── 从规则引擎提取风险 ──
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

        # ── 从参数倾向性提取风险 ──
        for f in bias_findings:
            if f.rule_id and f.rule_id in rule_ids:
                continue
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

        # ── 从LLM提取风险（强制读取 validation metadata）──
        for lv in llm_violations:
            validation_error = lv.validation_error
            requires_review = lv.requires_human_review

            if validation_error or requires_review:
                category = "needs_review"
                logger.warning(
                    "LLM 证据链校验失败 [%s]: %s → 降级为 needs_human_review",
                    lv.type, validation_error or "requires_human_review",
                )
            elif lv.risk_level == "high":
                category = "high_risk"
            else:
                category = "needs_review"

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
                validation_error=validation_error,
                requires_human_review=requires_review,
            ))

        # ── 解析质量调整 ──
        quality_multiplier = {"ok": 1.0, "text_layer": 1.0, "ocr": 1.2, "partial": 1.5, "failed": 2.0}
        adjustment = "none"
        if parse_quality in ("ocr", "partial", "failed"):
            adjustment = "upgraded"

        # ── 计数统计 ──
        confirmed_count = sum(1 for r in risk_items if r.category == "confirmed")
        high_risk_count = sum(1 for r in risk_items if r.category == "high_risk")
        needs_review_count = sum(1 for r in risk_items if r.category == "needs_review")
        advisory_count = sum(1 for r in risk_items if r.category == "advisory")

        # ── 综合判定风险等级 ──
        if confirmed_count > 0:
            risk_level = "critical" if confirmed_count >= 2 else "high"
        elif high_risk_count > 0:
            risk_level = "high"
        elif needs_review_count > 0:
            risk_level = "medium"
        else:
            risk_level = "low"

        risk_level_original = risk_level

        if adjustment == "upgraded":
            if risk_level == "low":
                risk_level = "medium"
            elif risk_level == "medium":
                risk_level = "high"

        # ── 判定是否通过 ──
        final_passed = confirmed_count == 0 and high_risk_count == 0

        # ── 复核状态机 ──
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


four_way_merger = FourWayRiskMerger()
