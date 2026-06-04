"""轻量级规则引擎 —— 招标文件硬性合规检查

规则类型：
  - chapter_required  : 检测招标文件必备章节是否存在
  - keyword_required  : 检测必备关键字是否出现在指定章节
  - forbidden         : 检测排他性/倾向性禁用词

支持从 JSON 文件加载规则、热重载、分级评分。
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field

# 共享类型：Violation / RuleEngineResult 提取到 shared_types，消除循环导入
from app.engine.shared_types import RuleEngineResult, Violation

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

class RuleDefinition(BaseModel):
    """单条规则定义（来自 JSON 配置）"""
    id: str
    type: str = Field(
        ...,
        pattern=r"^(chapter_required|keyword_required|forbidden|format_required)$",
    )
    target: str = ""
    weight: float = 10.0
    description: str = ""
    law_ref: Optional[str] = None
    suggestion: str = ""
    category: str = "base"
    keyword: Optional[str] = None        # 关键字规则：必备关键字
    target_section: Optional[str] = None # 关键字规则：期望关键字所在的章节
    pattern: Optional[str] = None        # 禁用词规则：正则匹配模式
    severity: str = "medium"             # 禁用词规则：严重程度
    exclude_contexts: Optional[list[str]] = None  # 禁用词排除上下文（FORB-008 等）


# Violation 和 RuleEngineResult 已迁移到 app.engine.shared_types
# 此处不再重复定义，直接通过 import 引入供外部使用
__all__ = ["RuleDefinition", "Violation", "RuleEngineResult", "RuleEngine", "rule_engine"]


# ── 默认路径常量 ─────────────────────────────────────────────
_RULES_DIR_DEFAULT = (
    "/app/rules" if os.path.exists("/app") else
    str(Path(__file__).resolve().parent.parent.parent.parent / "rules")
)

# ── 章节同义词反向映射 ──────────────────────────────────────
# 保证 JSON 规则中的 target 与 Parser 输出的标准化章节类型对齐
# 例如规则 target="投标人须知" → 解析器规范化类型="投标须知"
_SECTION_SYNONYM_MAP: dict[str, str] = {
    "招标公告": "招标公告",
    "投标邀请": "招标公告",
    "采购公告": "招标公告",
    "招标邀请": "招标公告",
    "投标邀请书": "招标公告",
    "竞争性谈判公告": "招标公告",
    "招标范围": "招标范围",
    "采购范围": "招标范围",
    "项目概况": "招标范围",
    "项目背景": "招标范围",
    "项目概述": "招标范围",
    "采购内容": "招标范围",
    "项目概述与招标范围": "招标范围",
    "资格要求": "资格要求",
    "投标人资格": "资格要求",
    "供应商资格": "资格要求",
    "资质要求": "资格要求",
    "合格投标人": "资格要求",
    "投标人资格要求": "资格要求",
    "申请人资格要求": "资格要求",
    "评审办法": "评审办法",
    "评标办法": "评审办法",
    "评审方法": "评审办法",
    "评分标准": "评审办法",
    "评分细则": "评审办法",
    "评审标准": "评审办法",
    "评标标准": "评审办法",
    "综合评分法": "评审办法",
    "投标须知": "投标须知",
    "投标人须知": "投标须知",
    "投标说明": "投标须知",
    "投标要求": "投标须知",
    "投标人须知前附表": "投标须知",
    "投标人须知及前附表": "投标须知",
    "合同条款": "合同条款",
    "合同草案": "合同条款",
    "合同主要条款": "合同条款",
    "采购合同": "合同条款",
    "合同文本": "合同条款",
    "投标文件格式": "投标文件格式",
    "投标文件组成": "投标文件格式",
    "投标文件编制": "投标文件格式",
    "投标文件的编制": "投标文件格式",
    "投标保证金": "投标保证金",
    "预算金额":"预算金额",
    "预算控制价":"预算金额",
    "最高限价":"预算金额",
    "报价要求":"报价要求",
    "履约要求":"履约要求",
    "保密条款":"保密条款",
    "知识产权":"知识产权",
    "招标项目需求": "招标范围",          # 规则 SEC-003 target → 归入招标范围
    "投标人": "资格要求",               # 广义关联
    "技术规格": "招标范围",
    "验收标准": "验收标准",
    "耗材与配件": "耗材与配件",
}


# ═══════════════════════════════════════════════════════════════
# 规则引擎核心
# ═══════════════════════════════════════════════════════════════

class RuleEngine:
    """
    轻量规则引擎：章节完整性 → 关键字合规 → 禁用词检测

    使用方式::
        engine = RuleEngine()
        result = engine.run(sections={"招标公告": "……"}, full_text="……全文……")
        for v in result.violations:
            print(v.rule_id, v.description)
    """

    def __init__(
        self,
        rules_dir: str | Path | None = None,
        industry: str | None = None,
        industries: list[str] | None = None,
    ):
        self.rules_dir = Path(rules_dir) if rules_dir else Path(_RULES_DIR_DEFAULT)
        self.rules: list[RuleDefinition] = []
        self.platform_mapping: dict[str, list[dict]] = {}
        self.industry: str | None = None
        self.active_industries: list[str] = []
        if industries:
            self.set_active_industries(industries)
        else:
            self._load_rules(industry=industry)

    # ── 规则加载 ────────────────────────────────────────────

    def _load_rules(self, industry: str | None = None) -> None:
        """
        从 JSON 规则文件加载所有规则。

        加载顺序：
        1. 基础规则（章节完整性 + 关键字）
        2. 禁用词规则
        3. 行业细分规则（industry 参数指定时）
        4. 平台规则映射
        """
        base_path = self.rules_dir / "base_rules.json"
        platform_path = self.rules_dir / "platform_rules.json"
        forbidden_path = self.rules_dir / "forbidden_words.json"

        self.rules.clear()
        self.industry = industry

        # 1. 基础规则（章节完整性 + 关键字）
        if base_path.exists():
            with open(base_path, encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("rules", [])
            self.rules = [RuleDefinition(**r) for r in raw]
            logger.info("已加载 %d 条基础规则（%s）", len(self.rules), base_path)
        else:
            logger.warning("规则文件不存在: %s", base_path)

        # 2. 禁用词规则
        if forbidden_path.exists():
            with open(forbidden_path, encoding="utf-8") as f:
                data = json.load(f)

            patterns_data = data.get("patterns", {})
            for category_name, cat_info in patterns_data.items():
                regex_list = cat_info.get("regex_list", [])
                default_severity = cat_info.get("severity", "medium")
                for item in regex_list:
                    self.rules.append(
                        RuleDefinition(
                            id=item.get("id", f"FORB-{len(self.rules)+1:03d}"),
                            type="forbidden",
                            target=item.get("pattern", ""),
                            weight=item.get("weight", 10),
                            description=item.get("message", ""),
                            suggestion=item.get("suggestion", ""),
                            pattern=item.get("pattern"),
                            severity=item.get("severity", default_severity),
                            law_ref=item.get("law_ref"),
                            category="base",
                            exclude_contexts=item.get("exclude_contexts"),
                        )
                    )

            logger.info("已加载 %d 条禁用词规则 (来自 %d 个分类)",
                        len([r for r in self.rules if r.type == "forbidden"]),
                        len(patterns_data))

        # 3. 行业细分规则
        if industry:
            industry_path = self.rules_dir / "industry" / f"{industry}.json"
            if industry_path.exists():
                with open(industry_path, encoding="utf-8") as f:
                    ind_data = json.load(f)
                ind_rules = ind_data.get("rules", [])
                industry_name = ind_data.get("industry", industry)
                for r in ind_rules:
                    self.rules.append(RuleDefinition(**r))
                logger.info(
                    "已加载 %d 条行业规则（%s: %s）",
                    len(ind_rules), industry_name, industry_path,
                )
            else:
                logger.warning("行业规则文件不存在: %s", industry_path)
        else:
            self.industry = None

        # 4. 平台规则映射 — 构建 rule_id → [platform_codes] 字典
        #    也按 rule_type + target 扩展匹配，实现跨平台规则对齐
        if platform_path.exists():
            with open(platform_path, encoding="utf-8") as f:
                data = json.load(f)
            for mapping in data.get("mappings", []):
                if not mapping.get("enabled", True):
                    continue
                entry = {
                    "platform": mapping["platform"],
                    "code": mapping.get("platform_code", ""),
                    "desc": mapping.get("description", ""),
                }
                # 精确 rule_id 匹配
                rule_id = mapping.get("rule_id", "")
                if rule_id:
                    self.platform_mapping.setdefault(rule_id, []).append(entry)

                # 按 type + target 模糊匹配（让平台规则可命中同类型的内部规则）
                rt = mapping.get("rule_type", "")
                tgt = mapping.get("target", "")
                if rt and tgt:
                    # 存储供 _match_platform_codes_by_target 使用
                    fuzzy_key = f"{rt}|{tgt}"
                    self.platform_mapping.setdefault(f"~fuzzy_{fuzzy_key}", []).append(entry)

        logger.info("规则引擎初始化完成，共 %d 条规则", len(self.rules))

    # ── 清单加载 ──────────────────────────────────────────

    @staticmethod
    def load_manifest(rules_dir: str | Path | None = None) -> dict:
        """
        从 rules/manifest.json 加载规则清单。

        Returns:
            manifest dict，如果文件不存在则返回默认清单
        """
        rd = Path(rules_dir) if rules_dir else Path(_RULES_DIR_DEFAULT)
        manifest_path = rd / "manifest.json"
        default = {
            "version": "1.0.0",
            "base_rules": "base_rules.json",
            "forbidden_words": "forbidden_words.json",
            "platform_mapping": "platform_rules.json",
            "industries": {},
            "prompts": "prompts/",
        }
        if manifest_path.exists():
            with open(manifest_path, encoding="utf-8") as f:
                data = json.load(f)
            logger.info("已加载规则清单: %s（v%s）", manifest_path, data.get("version", "?"))
            return data
        logger.info("规则清单不存在，使用默认路径: %s", manifest_path)
        return default

    def list_industries(self) -> list[str]:
        """返回 manifest 中注册的所有行业标识符"""
        manifest = self.load_manifest(self.rules_dir)
        return sorted(manifest.get("industries", {}).keys())

    # ── 热加载 ──────────────────────────────────────────

    def reload(self) -> None:
        """热加载规则文件（运行时调用，无需重启）"""
        if self.active_industries:
            self.set_active_industries(self.active_industries)
        else:
            self._load_rules(industry=self.industry)
        logger.info("规则已热加载（共 %d 条）", len(self.rules))

    def load_industry_rules(self, industry: str) -> int:
        """
        加载特定行业的附加规则（叠加在基础规则之上）。

        与 load_industry() 不同，此方法不替换现有规则，
        而是从 rules/industry/{industry}.json 加载行业规则追加到当前规则集。
        重复调用同一行业不会重复加载。

        Args:
            industry: 行业标识符，如 "it" / "construction" / "healthcare"

        Returns:
            新增的规则数量
        """
        # 如果规则集为空，先加载基础规则
        if not self.rules:
            self._load_rules()

        # 检查是否已加载
        prefix = f"IND-{industry.upper()[:2]}-"
        already_loaded = any(r.id.startswith(prefix) for r in self.rules)
        if already_loaded:
            logger.debug("行业 %s 规则已加载，跳过", industry)
            return 0

        industry_path = self.rules_dir / "industry" / f"{industry}.json"
        if not industry_path.exists():
            logger.warning("行业规则文件不存在: %s", industry_path)
            return 0

        with open(industry_path, encoding="utf-8") as f:
            ind_data = json.load(f)
        ind_rules = ind_data.get("rules", [])
        industry_name = ind_data.get("industry", industry)
        count = 0
        for r in ind_rules:
            self.rules.append(RuleDefinition(**r))
            count += 1

        if industry not in self.active_industries:
            self.active_industries.append(industry)

        logger.info(
            "已加载 %d 条行业规则（%s: %s），当前共 %d 条",
            count, industry_name, industry_path, len(self.rules),
        )
        return count

    def set_active_industries(self, industries: list[str]) -> dict[str, int]:
        """
        设置当前文档适用的行业规则（支持多选）。

        先加载基础规则，再依次加载每个行业的附加规则。
        可用于混合行业场景（如同时涉及 IT 和医疗的采购项目）。

        Args:
            industries: 行业标识符列表，如 ["it", "healthcare"]

        Returns:
            {industry: loaded_count, ...} 各行业加载的规则数
        """
        # 重新加载基础规则（清除旧的行业规则）
        self._load_rules()
        self.active_industries = []

        result: dict[str, int] = {}
        for ind in industries:
            count = self.load_industry_rules(ind)
            result[ind] = count

        logger.info(
            "已设置活跃行业 %s，共 %d 条规则",
            ", ".join(industries), len(self.rules),
        )
        return result

    # ── 辅助：按 type + target 匹配平台规则 ────────────────

    def _match_platform_codes(self, rule: RuleDefinition) -> list[dict]:
        """收集该规则对应的平台拦截代码"""
        codes = list(self.platform_mapping.get(rule.id, []))

        # 也按 type + target 模糊匹配
        rt = rule.type
        tgt = rule.target
        if rt and tgt:
            for source in (rule.target, rule.description or "", getattr(rule, "keyword", "") or ""):
                if not source:
                    continue
                for fuzzy_key, entries in list(self.platform_mapping.items()):
                    if not fuzzy_key.startswith("~fuzzy_"):
                        continue
                    parts = fuzzy_key.split("|", 2)
                    if len(parts) != 3:
                        continue
                    _, f_rt, f_tgt = parts
                    if f_rt in (rt, "") and f_tgt and (f_tgt in source or source in f_tgt):
                        for entry in entries:
                            if entry not in codes:
                                codes.append(entry)

        # 去重
        seen = set()
        deduped = []
        for c in codes:
            key = (c["platform"], c["code"])
            if key not in seen:
                seen.add(key)
                deduped.append(c)
        return deduped

    # ── 章节完整性检查 ──────────────────────────────────────

    def check_sections(
        self,
        parsed_sections: dict[str, str] | None = None,
        full_text: str = "",
    ) -> list[Violation]:
        """
        检查招标文件是否包含全部必备章节。

        Args:
            parsed_sections: 解析器输出的结构化章节 dict（推荐）
            full_text:        原始全文（parsed_sections 为空时做降级检测）

        Returns:
            缺失章节违规列表
        """
        violations: list[Violation] = []

        # 从规则中筛选所有章节完整性规则
        chapter_rules = [r for r in self.rules if r.type == "chapter_required"]
        if not chapter_rules:
            return violations

        if parsed_sections:
            # ★ 精确匹配：解析器给出的章节 type + 规则 target（经同义词归一）
            found_types = set(parsed_sections.keys())
            for rule in chapter_rules:
                canonical = _SECTION_SYNONYM_MAP.get(rule.target, rule.target)
                if canonical not in found_types:
                    violations.append(
                        Violation(
                            rule_id=rule.id,
                            rule_type="chapter_required",
                            description=rule.description or f"缺少《{rule.target}》章节",
                            risk_level="high",
                            suggestion=rule.suggestion or f"请补充《{rule.target}》章节",
                            weight=rule.weight,
                            platform_codes=self._match_platform_codes(rule),
                            law_ref=rule.law_ref,
                        )
                    )
        else:
            # 降级：从全文正则提取章节标题后做模糊匹配
            found = self._extract_chapters(full_text)
            for rule in chapter_rules:
                target = rule.target
                if not any(target in ch or ch in target for ch in found):
                    violations.append(
                        Violation(
                            rule_id=rule.id,
                            rule_type="chapter_required",
                            description=rule.description or f"缺少《{target}》相关内容",
                            risk_level="high",
                            suggestion=rule.suggestion or f"请补充《{target}》章节",
                            weight=rule.weight,
                            platform_codes=self._match_platform_codes(rule),
                            law_ref=rule.law_ref,
                        )
                    )

        return violations

    # ── 关键字合规检查 ──────────────────────────────────────

    def check_keywords(
        self,
        sections: dict[str, str],
        marked_doc: Any | None = None,
    ) -> list[Violation]:
        """
        检查必备关键字是否出现在指定章节。

        定变分离优化：
        - 指纹库模式（method=fingerprint）：只检查 VARIABLE + UNCERTAIN 区域的文本，
          FIXED 区域的关键字缺失不视为违规（模板固定内容）
        - 启发式模式（method=heuristic 或无指纹库）：使用原始章节文本，
          避免因启发式标记不可靠导致漏检

        Args:
            sections:   解析器输出的章节 dict
            marked_doc: 定变分离标记后的文档（可选）

        Returns:
            关键字缺失违规列表
        """
        violations: list[Violation] = []
        keyword_rules = [r for r in self.rules if r.type == "keyword_required"]

        # ── 判断标记方法的可靠性 ──────────────────────────────
        is_fingerprint_mode = (
            marked_doc is not None
            and hasattr(marked_doc, 'stats')
            and marked_doc.stats.get("method") == "fingerprint"
        )

        for rule in keyword_rules:
            # 确定检查范围：指定章节（经同义词归一）或全文
            target_sec = _SECTION_SYNONYM_MAP.get(rule.target_section, rule.target_section) if rule.target_section else None
            if target_sec:
                target_text = sections.get(target_sec, "")

                # 定变分离：仅在指纹库模式下信任 VARIABLE 过滤
                if is_fingerprint_mode and hasattr(marked_doc, 'get_variable_text'):
                    variable_text = marked_doc.get_variable_text(target_sec)
                    # 如果变量文本为空（可能全部被标为 FIXED），回退到原始文本
                    if variable_text.strip():
                        target_text = variable_text
                    else:
                        logger.debug(
                            "章节 [%s] 的变量文本为空，回退到原始文本进行关键字检查 (%d 字符)",
                            target_sec, len(target_text),
                        )
            else:
                if is_fingerprint_mode and hasattr(marked_doc, 'get_variable_text'):
                    variable_text = marked_doc.get_variable_text()
                    if variable_text.strip():
                        target_text = variable_text
                    else:
                        target_text = "\n".join(sections.values())
                else:
                    target_text = "\n".join(sections.values())

            if rule.keyword and rule.keyword not in target_text:
                risk = "high" if rule.weight >= 15 else "medium"
                location = (
                    f"应在《{target_sec}》中" if target_sec
                    else "全文"
                )
                violations.append(
                    Violation(
                        rule_id=rule.id,
                        rule_type="keyword_required",
                        description=rule.description or f"缺少关键字「{rule.keyword}」",
                        location=location,
                        risk_level=risk,
                        suggestion=rule.suggestion or f"请补充「{rule.keyword}」相关表述",
                        weight=rule.weight,
                        platform_codes=self._match_platform_codes(rule),
                        law_ref=rule.law_ref,
                    )
                )

        return violations

    # ── 禁用词检测 ──────────────────────────────────────────

    def check_forbidden_words(
        self,
        sections: dict[str, str],
        marked_doc: Any | None = None,
    ) -> list[Violation]:
        """
        逐章节扫描禁用词/排他性表述。

        定变分离优化：
        - 指纹库模式（method=fingerprint）：FIXED 区域的匹配被跳过
          （视为模板固定内容，非代理机构填写），UNCERTAIN 区域标记但保留
        - 启发式模式（method=heuristic 或无指纹库）：所有匹配均保留，
          不因 FIXED 标签跳过，仅标记 span_label 供参考

        Args:
            sections:   解析器输出的章节 dict
            marked_doc: 定变分离标记后的文档（可选）

        Returns:
            命中禁用词违规列表
        """
        violations: list[Violation] = []
        forbidden_rules = [r for r in self.rules if r.type == "forbidden"]

        # ── 判断标记方法的可靠性 ──────────────────────────────
        is_fingerprint_mode = (
            marked_doc is not None
            and hasattr(marked_doc, 'stats')
            and marked_doc.stats.get("method") == "fingerprint"
        )

        for rule in forbidden_rules:
            pattern_str = rule.pattern if rule.pattern else re.escape(rule.target)
            try:
                pattern = re.compile(pattern_str, re.IGNORECASE)
            except re.error as exc:
                logger.warning("禁用词规则 %s 正则编译失败: %s", rule.id, exc)
                continue

            for sec_name, sec_text in sections.items():
                # ── 定变分离：获取该章节的文本段列表 ──────────
                spans = None
                if marked_doc and hasattr(marked_doc, 'sections'):
                    spans = marked_doc.sections.get(sec_name)

                for match in pattern.finditer(sec_text):
                    # 上下文排除：如果规则定义了 exclude_contexts，检查匹配片段是否在排除上下文中
                    if rule.exclude_contexts:
                        match_text = match.group()
                        ctx_start = max(0, match.start() - 10)
                        ctx_end = min(len(sec_text), match.end() + 10)
                        surrounding = sec_text[ctx_start:ctx_end]
                        if any(exc in surrounding for exc in rule.exclude_contexts):
                            continue  # 排除上下文，跳过此匹配

                    # ── 定变分离过滤 ──────────────────────
                    span_label = ""
                    is_fp = False
                    tp_conf = 0.0

                    if spans:
                        span_label = self._find_span_label(
                            spans, match.start(), match.end()
                        )
                        # 仅在指纹库模式下信任 FIXED 标签跳过匹配
                        if is_fingerprint_mode and span_label == "FIXED":
                            logger.debug(
                                "跳过规则 %s 在 [%s] 的匹配（FIXED 模板区域，指纹库模式）: %s",
                                rule.id, sec_name, match.group()[:50],
                            )
                            continue
                        # UNCERTAIN 区域的匹配 → 标记但保留
                        if span_label == "UNCERTAIN":
                            is_fp = False  # 不确定，保留但让用户判断
                            tp_conf = 0.4
                        # 启发式模式下的 FIXED 标签不可靠 → 保留匹配，标记降低置信度
                        if not is_fp and span_label == "FIXED":
                            tp_conf = 0.3  # 低置信度：启发式 FIXED 不可靠
                            logger.debug(
                                "规则 %s 在 [%s] 启发式 FIXED 区域匹配，保留供审核: %s",
                                rule.id, sec_name, match.group()[:50],
                            )

                    # 计算近似行号
                    line_no = sec_text[: match.start()].count("\n") + 1
                    context_start = max(match.start() - 20, 0)
                    context = sec_text[context_start : match.end() + 20].replace("\n", " ")

                    violations.append(
                        Violation(
                            rule_id=rule.id,
                            rule_type="forbidden",
                            description=rule.description or f"发现禁用词: {match.group()}",
                            location=f"{sec_name} ~第{line_no}行",
                            text=context.strip(),
                            risk_level=rule.severity,
                            suggestion=rule.suggestion or f"请修改「{match.group()}」相关表述",
                            weight=rule.weight,
                            platform_codes=self._match_platform_codes(rule),
                            law_ref=rule.law_ref,
                            span_label=span_label,
                            is_template_false_positive=is_fp,
                            template_confidence=tp_conf,
                        )
                    )

        return violations

    # ── 格式规范关键字检查（format_required 规则的具体实现） ──

    def check_format_keywords(self, sections: dict[str, str]) -> list[Violation]:
        """
        检查 format_required 规则对文档的格式规范要求（密封/签章/页码/装订等）。

        与 keyword 检查类似，在全文和指定章节中检测对应的规范性关键词。
        如果文档中未提及这些格式要求，认为需要提示补充。
        """
        violations: list[Violation] = []
        fmt_rules = [r for r in self.rules if r.type == "format_required"]

        # format_required 规则 → 对应的搜索关键词
        FORMAT_KEYWORD_MAP: dict[str, str] = {
            "页码": "页码",
            "密封要求": "密封",
            "签章要求": "签章",
            "电子投标": "电子投标",
            "装订要求": "装订",
            "目录编排": "目录",
            "光盘/U盘": "光盘",
        }

        for rule in fmt_rules:
            kw = FORMAT_KEYWORD_MAP.get(rule.target, rule.target)
            found = False
            for sec_text in sections.values():
                if kw in sec_text:
                    found = True
                    break
            if not found:
                violations.append(
                    Violation(
                        rule_id=rule.id,
                        rule_type="format_required",
                        description=rule.description or f"缺少格式规范：{rule.target}",
                        risk_level="low",
                        suggestion=rule.suggestion or f"请补充关于{rule.target}的格式要求",
                        weight=rule.weight,
                        platform_codes=self._match_platform_codes(rule),
                        law_ref=rule.law_ref,
                    )
                )

        return violations

    # ── 定变分离辅助 ──────────────────────────────────────

    @staticmethod
    def _find_span_label(spans: list[Any], match_start: int, match_end: int) -> str:
        """查找匹配位置所在的文本段标签

        遍历章节的 TextSpan 列表，找到包含 match_start..match_end
        偏移区间的 span，返回其 label。

        由于我们在原始文本上做正则匹配（而非在拼接后的 VARIABLE 文本上），
        我们累积偏移找到匹配位置所属的 span。

        Args:
            spans: 该章节的 TextSpan 列表
            match_start: 正则匹配在原始章节文本中的起始位置
            match_end:   正则匹配在原始章节文本中的结束位置

        Returns:
            "FIXED" | "VARIABLE" | "UNCERTAIN" | "" (找不到时)
        """
        cumulative = 0
        for span in spans:
            span_start = cumulative
            span_end = cumulative + span.length
            # 匹配位置与 span 有重叠
            if match_start < span_end and match_end > span_start:
                return span.label
            cumulative = span_end
            # 考虑句子间的分隔符（换行/空格等）
            cumulative += 1  # 估算分隔符
        return ""

    @staticmethod
    def _calc_score(violations: list[Violation]) -> float:
        """
        从违规列表计算扣分后的得分（百分制），使用阶梯衰减防止单维度归零。

        计分策略：
        - 使用对数衰减：首条违规权重全额扣分，后续按对数递减（√n 衰减）
        - 单个违规最多扣 weight*1.0 分，后续同维度违规边际扣分递减
        - 这样 5 条 10-weight 的违规扣约 42 分而非 50 分，
          10 条扣约 63 分而非 100 分
        - 总分不封底到 0，最低保留 5 分以区别于「无内容」场景

        公式：deduction = Σ(weight_i * 1.0 / sqrt(rank_i))
              其中 rank_i 是该违规在同维度中的序号（1-based）
        """
        if not violations:
            return 100.0

        import math
        # 按 weight 降序排列，让高权重违规排前面（扣分更多）
        sorted_v = sorted(violations, key=lambda v: v.weight, reverse=True)
        deduction = sum(
            v.weight * 1.0 / math.sqrt(i + 1)
            for i, v in enumerate(sorted_v)
        )
        # 最低保留 5 分
        return round(max(5.0, 100.0 - deduction), 1)

    # ── 统一入口 ────────────────────────────────────────────

    def run(
        self,
        sections: dict[str, str],
        full_text: str = "",
        marked_doc: Any | None = None,
    ) -> RuleEngineResult:
        """
        执行完整的规则检查流水线：
          章节完整性 → 关键字合规 → 禁用词检测（含 format_required 关键字验证）

        定变分离优化：
        - 章节完整性检查：不受影响（始终检查全文——章节存在性是结构要求）
        - 关键字检查：仅在 VARIABLE + UNCERTAIN 区域检查
        - 禁用词检查：跳过 FIXED 区域的匹配

        Args:
            sections:   文档解析器输出的结构化章节（章节名 → 正文）
            full_text:  全文文本（章节完整性降级检测使用）
            marked_doc: 定变分离标记后的文档（可选，提供时启用智能过滤）

        Returns:
            RuleEngineResult
        """
        section_violations = self.check_sections(parsed_sections=sections, full_text=full_text)
        keyword_violations = self.check_keywords(sections, marked_doc=marked_doc)
        forbidden_violations = self.check_forbidden_words(sections, marked_doc=marked_doc)
        format_violations = self.check_format_keywords(sections)

        all_violations = section_violations + keyword_violations + forbidden_violations + format_violations

        # 统计模板误报数
        tp_count = sum(1 for v in all_violations if v.is_template_false_positive)
        if tp_count > 0:
            logger.info("规则引擎检测到 %d 条模板误报（已跳过FIXED区域匹配）", tp_count)

        return RuleEngineResult(
            violations=all_violations,
            section_score=self._calc_score(section_violations),
            keyword_score=self._calc_score(keyword_violations),
            forbidden_score=self._calc_score(forbidden_violations),
            total_score=self._calc_score(all_violations),
        )

    # ── 辅助：全文降级章节抽取 ──────────────────────────────

    @staticmethod
    def _extract_chapters(text: str) -> list[str]:
        """
        从全文文本中正则提取章节标题（降级兜底用）。
        优先使用解析器输出的结构化 sections。
        """
        chapters: list[str] = []
        patterns = [
            re.compile(r"^第[一二三四五六七八九十\d]+[章节节部分]\s*(.+?)$", re.MULTILINE),
            re.compile(r"^[一二三四五六七八九十]+[、\.\s]\s*(.+)$", re.MULTILINE),
            re.compile(r"^\d+[、\.\s]\s*(.+)$", re.MULTILINE),
        ]
        for pat in patterns:
            for m in pat.finditer(text):
                title = m.group(1).strip()
                if title and title not in chapters:
                    chapters.append(title)
        return chapters


# 模块级单例（兼容已有导入）
rule_engine = RuleEngine()
