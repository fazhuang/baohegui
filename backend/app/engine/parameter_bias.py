"""参数倾向性检测引擎

第2层审查：基于558个甘肃政府采购投诉案例提炼的9种违规模式，
对技术参数和资格要求进行模式匹配检测。

核心检测：品牌锁定、厂家授权锁、组合参数整体指向性（最高级别的隐性排他）。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from app.engine.shared_types import BiasFinding, ParameterBiasResult

logger = logging.getLogger(__name__)

# ── 规则文件路径 ──────────────────────────────────────────────
_RULES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "rules"
_BIAS_RULES_PATH = _RULES_DIR / "parameter_bias_rules.json"


class ParameterBiasDetector:
    """参数倾向性检测器"""

    def __init__(self, rules_path: Optional[Path] = None):
        self._rules_path = rules_path or _BIAS_RULES_PATH
        self._patterns: dict = {}
        self._load_rules()

    def _load_rules(self) -> None:
        """加载参数倾向性检测规则"""
        try:
            with open(self._rules_path, "r", encoding="utf-8") as f:
                rules_data = json.load(f)
            self._patterns = rules_data.get("violation_patterns", {})
            logger.info(
                "参数倾向性规则加载完成: %d 种违规模式",
                len(self._patterns),
            )
        except Exception as e:
            logger.warning("参数倾向性规则加载失败: %s，使用空规则集", e)
            self._patterns = {}

    def run(self, sections: dict[str, str]) -> ParameterBiasResult:
        """
        对文档各章节执行参数倾向性检测。

        Args:
            sections: 章节名 → 章节内容 的映射

        Returns:
            ParameterBiasResult with all findings and risk score
        """
        all_findings: list[BiasFinding] = []

        for section_name, content in sections.items():
            if not content:
                continue

            # 根据章节类型选择适用的检测字段
            is_qual = any(kw in section_name for kw in ["资格", "资质"])
            is_tech = any(kw in section_name for kw in ["技术", "参数", "规格", "需求"])
            is_score = any(kw in section_name for kw in ["评审", "评分", "评标"])

            check_fields: list[str] = []
            if is_qual:
                check_fields.append("qualification_requirements")
            if is_tech:
                check_fields.append("technical_params")
            if is_score:
                check_fields.append("evaluation_criteria")
            if not check_fields:
                check_fields.append("general")

            for field in check_fields:
                findings = self._check_section(content, field)
                all_findings.extend(findings)

        # ── 计算风险评分 ──────────────────────────────────────
        critical_count = sum(1 for f in all_findings if f.severity == "critical")
        high_count = sum(1 for f in all_findings if f.severity == "high")
        medium_count = sum(1 for f in all_findings if f.severity == "medium")

        risk_score = min(100.0,
            critical_count * 25.0 + high_count * 12.0 + medium_count * 5.0
        )

        logger.info(
            "参数倾向性检测完成: %d发现 (严重:%d 高:%d 中:%d) 风险分:%.1f",
            len(all_findings), critical_count, high_count, medium_count, risk_score,
        )

        return ParameterBiasResult(
            findings=all_findings,
            total_checks=len(self._patterns),
            risk_score=round(risk_score, 1),
            critical_count=critical_count,
            high_count=high_count,
        )

    def _check_section(self, text: str, field: str) -> list[BiasFinding]:
        """对单个章节内容执行所有适用模式的检测"""
        findings: list[BiasFinding] = []
        for pattern_id, pattern_def in self._patterns.items():
            check_fields = pattern_def.get("check_fields", [])
            if field not in check_fields and "general" not in check_fields:
                continue
            # Try dedicated method first, fallback to generic
            method_name = f"_check_{pattern_id}"
            checker = getattr(self, method_name, None)
            if checker:
                try:
                    result = checker(text, field)
                    findings.extend(result)
                except Exception as e:
                    logger.debug("检测模式 %s 执行异常: %s", pattern_id, e)
            else:
                findings.extend(self._check_generic_pattern(text, field, pattern_id, pattern_def))
        return findings

    def _check_generic_pattern(
        self, text: str, field: str, pattern_id: str, pattern_def: dict
    ) -> list[BiasFinding]:
        """通用关键词匹配检测"""
        keywords = pattern_def.get("keywords", [])
        findings: list[BiasFinding] = []
        for kw in keywords:
            # Convert wildcard * to regex
            kw_pattern = kw.replace("*", r"\S*")
            if re.search(kw_pattern, text):
                findings.append(BiasFinding(
                    pattern_id=pattern_id,
                    pattern_name=pattern_def.get("description", pattern_id),
                    severity=pattern_def.get("severity", "medium"),
                    matched_text=kw,
                    matched_field=field,
                    confidence=0.7,
                    description=pattern_def.get("check_logic", ""),
                    suggestion=pattern_def.get("suggestion", ""),
                    rule_id=pattern_def.get("rule_id"),
                ))
                break  # One finding per pattern
        return findings

    # ── Dedicated detection methods ──────────────────────────

    def _check_brand_lock_series(self, text: str, field: str) -> list[BiasFinding]:
        """品牌锁定检测：要求同品牌/品牌一致"""
        patterns = [
            (r"(?:须|必须|应|应当|需要|要求).{0,10}(?:同一品牌|同品牌)", 0.85),
            (r"(?:同一品牌|同品牌)", 0.70),
            (r"品牌(?:\s*)一致", 0.80),
            (r"(?:须|必须).{0,10}配套品牌", 0.75),
        ]
        for pat, confidence in patterns:
            match = re.search(pat, text)
            if match:
                return [BiasFinding(
                    pattern_id="brand_lock_series",
                    pattern_name="品牌锁定",
                    severity="critical",
                    matched_text=match.group(0),
                    matched_field=field,
                    confidence=confidence,
                    description="要求不同设备/产品为同一品牌，限制竞争",
                    suggestion="不同设备可采用不同品牌，只要满足互联互通标准即可",
                    rule_id="R107",
                )]
        return []

    def _check_manufacturer_authorization(self, text: str, field: str) -> list[BiasFinding]:
        """厂家授权锁检测"""
        patterns = [
            (r"(?:厂家授权|原厂授权|制造商授权)", 0.80),
            (r"(?:厂家盖章|原厂公章|厂商授权书)", 0.75),
            (r"原厂售后服务承诺", 0.85),
        ]
        for pat, confidence in patterns:
            match = re.search(pat, text)
            if match:
                return [BiasFinding(
                    pattern_id="manufacturer_authorization",
                    pattern_name="厂家授权锁",
                    severity="high",
                    matched_text=match.group(0),
                    matched_field=field,
                    confidence=confidence,
                    description="要求投标前取得厂家授权/售后服务承诺函，限制代理商竞争",
                    suggestion="可在中标后提供厂家授权或取消此要求",
                    rule_id="R101",
                )]
        return []

    def _check_detection_report_lock(self, text: str, field: str) -> list[BiasFinding]:
        """检测报告锁定"""
        match = re.search(r"(?:CMA|CNAS|检测报告|检测证明|检验报告|型式检验)", text)
        if match:
            return [BiasFinding(
                pattern_id="detection_report_lock",
                pattern_name="检测报告锁定",
                severity="high",
                matched_text=match.group(0),
                matched_field=field,
                confidence=0.75,
                description="要求提供特定机构出具的检测报告",
                suggestion="允许提供第三方检测报告即可，不限定机构",
                rule_id="R109",
            )]
        return []

    def _check_parameter_exclusivity(self, text: str, field: str) -> list[BiasFinding]:
        """参数指向性检测"""
        # Only flag when restrictive language accompanies parameter/spec references
        patterns = [
            (r"(?:参数|指标|规格).{0,15}(?:唯一|仅|只能|限定|指定|特定|不少于|不低于|不高于)", 0.75),
            (r"(?:仅|只能|限定|指定|特定).{0,10}(?:参数|指标|规格|配置)", 0.80),
            (r"(?:(?:\d+(?:\.\d+)?)\s*(?:W|mm|cm|m|kg|g|L|ml|℃|°C|dB|Hz|kHz|MHz|GHz|V|A|Ω|W|lux|lm|m/s|km/h|rpm)|(?:功率|尺寸|重量|容量|频率|电压|电流)).{0,10}(?:参数|指标|规格)", 0.65),
        ]
        for pat, confidence in patterns:
            match = re.search(pat, text)
            if match:
                return [BiasFinding(
                    pattern_id="parameter_exclusivity",
                    pattern_name="参数指向性",
                    severity="high",
                    matched_text=match.group(0),
                    matched_field=field,
                    confidence=confidence,
                    description="参数数值范围可能过窄，需人工确认是否至少3个品牌可满足",
                    suggestion="至少3个品牌可满足每个核心参数",
                    rule_id="AI-BIAS-004",
                )]
        return []

    def _check_standard_not_exists(self, text: str, field: str) -> list[BiasFinding]:
        """引用无效标准版本检测"""
        # Only flag when a standard reference looks like a versioned standard
        # (GB/T XXXXX-YYYY pattern) or an obsolete reference, not bare "GB" or "标准"
        patterns = [
            (r"GB[/T]?\s*\d+(?:\.\d+)?[-—]\d{4}", 0.85),
            (r"(?:废止|失效|过期).{0,10}(?:标准|规范)", 0.80),
            (r"(?:标准|规范).{0,10}(?:废止|失效|过期)", 0.80),
        ]
        for pat, confidence in patterns:
            match = re.search(pat, text)
            if match:
                return [BiasFinding(
                    pattern_id="standard_not_exists",
                    pattern_name="引用无效标准版本",
                    severity="high",
                    matched_text=match.group(0),
                    matched_field=field,
                    confidence=confidence,
                    description="引用标准需核实是否存在且现行有效",
                    suggestion="核实引用标准的有效性，使用现行有效版本",
                    rule_id="AI-BIAS-010",
                )]
        return []
