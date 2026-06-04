"""招标文件定变分离标记器

核心模块：在审查流程前预处理文档，区分：
- FIXED（定量）：标准模板中的固定框架文字 → 不应作为违规审查对象
- VARIABLE（变量）：代理机构实际填写的个性化内容 → 合规风险的真实来源
- UNCERTAIN（不确定）：无法明确判断的边界文本 → 保守处理，仍参与审查

标记流程：
1. 句子级别分割
2. 与 STDT 模板指纹库精确/模糊匹配
3. 占位符模式识别
4. 上下文推断（连续固定块中的短句）
5. 回退：无指纹库时用启发式规则
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from app.services.parser import ParsedDocument

logger = logging.getLogger(__name__)

# ── 占位符检测正则（与 fingerprint 中一致）─────────────────
_VARIABLE_MARKER_PATTERNS = [
    re.compile(r"[（(][^）)]*?(?:项目名称|采购人|招标人|供应商|投标人|金额|日期|时间|地点|地址|名称|编号|数量|规格|参数|要求|内容|说明|填写|自定|根据|视情|协商|约定)[^）)]*?[）)]"),
    re.compile(r"[（(][^）)]{0,30}[）)]"),
    re.compile(r"【[^】]{0,50}】"),
    re.compile(r"[Xx_＿]{2,}"),
    re.compile(r"(?:根据项目|根据实际|视项目|按项目|协商|约定|自定|参照).{0,20}(?:确定|执行|处理|填写)"),
    re.compile(r"此处.*?(?:填写|填入|插入|自定|自定义)"),
    re.compile(r"详见.{0,20}(?:附件|附表|下文|下表|要求)"),
    re.compile(r"□"),
]

# ── 章节标题模式 ───────────────────────────────────────────
_HEADING_PATTERN = re.compile(
    r'^(?:第[一二三四五六七八九十\d]+[章节条]|'
    r'[一二三四五六七八九十]+[、\.,，]|'
    r'\d+[\.\、]|'
    r'[（(][一二三四五六七八九十\d]+[)）])'
)

# ── 文本归一化 ─────────────────────────────────────────────
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[。！？；\n])\s*')


def _normalize(text: str) -> str:
    """轻量归一化：去多余空白"""
    return re.sub(r'\s+', '', text)


# ── 数据结构 ────────────────────────────────────────────────

@dataclass
class TextSpan:
    """标记后的文本段"""
    text: str
    label: str = "VARIABLE"      # FIXED | VARIABLE | UNCERTAIN
    confidence: float = 0.7
    fingerprint_id: str | None = None
    section_type: str = ""       # 所属标准化章节类型
    char_offset: int = 0         # 在原始文本中的偏移
    length: int = 0

    def __post_init__(self):
        self.length = len(self.text)


@dataclass
class MarkedDocument:
    """定变分离后的文档"""
    filename: str
    sections: dict[str, list[TextSpan]] = field(default_factory=dict)
    full_text: str = ""
    stats: dict = field(default_factory=dict)
    sector: str = ""
    procurement_method: str = ""
    project_type: str = ""

    def get_variable_text(self, section_type: str = "") -> str:
        """获取指定章节的变量文本（仅 VARIABLE + UNCERTAIN 标记的文本段）"""
        result: list[str] = []
        target_sections = (
            {section_type: self.sections[section_type]}
            if section_type and section_type in self.sections
            else self.sections
        )
        for spans in target_sections.values():
            for span in spans:
                if span.label != "FIXED":
                    result.append(span.text)
        return "\n".join(result)

    def get_all_text(self, section_type: str = "") -> str:
        """获取指定章节的完整文本（含 FIXED）"""
        result: list[str] = []
        target_sections = (
            {section_type: self.sections[section_type]}
            if section_type and section_type in self.sections
            else self.sections
        )
        for spans in target_sections.values():
            for span in spans:
                result.append(span.text)
        return "\n".join(result)

    def get_spans_for_checking(self, section_type: str = "",
                               include_uncertain: bool = True) -> list[TextSpan]:
        """获取需要审查的文本段列表"""
        result: list[TextSpan] = []
        target_sections = (
            {section_type: self.sections[section_type]}
            if section_type and section_type in self.sections
            else self.sections
        )
        for spans in target_sections.values():
            for span in spans:
                if span.label == "VARIABLE":
                    result.append(span)
                elif span.label == "UNCERTAIN" and include_uncertain:
                    result.append(span)
        return result

    def get_text_for_llm(self, section_type: str = "") -> str:
        """构建适合 LLM 审查的标记文本

        格式：
        <<TEMPLATE>> 固定内容 <</TEMPLATE>>
        <<REVIEW>> 变量内容需要审查 <</REVIEW>>
        """
        result: list[str] = []
        target_sections = (
            {section_type: self.sections[section_type]}
            if section_type and section_type in self.sections
            else self.sections
        )
        for sec_type, spans in target_sections.items():
            result.append(f"\n=== {sec_type} ===")
            current_label = None
            buffer: list[str] = []

            def flush_buffer():
                nonlocal current_label, buffer
                if not buffer:
                    return
                text = " ".join(buffer)
                if current_label == "FIXED":
                    result.append(f"<<TEMPLATE>>\n{text}\n<</TEMPLATE>>")
                else:
                    result.append(f"<<REVIEW>>\n{text}\n<</REVIEW>>")
                buffer = []

            for span in spans:
                if span.label != current_label:
                    flush_buffer()
                    current_label = span.label
                buffer.append(span.text)
            flush_buffer()

        return "\n".join(result)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "sections": {
                sec: [{"text": s.text[:100], "label": s.label, "confidence": s.confidence}
                      for s in spans]
                for sec, spans in self.sections.items()
            },
            "stats": self.stats,
        }


# ── 启发式标记器（无指纹库降级方案）─────────────────────────

# 固定内容语义特征
_FIXED_INDICATORS = [
    (re.compile(r'(?:招标投标法|政府采购法|实施条例|财政部令|号令|号文)'), 3),
    (re.compile(r'(?:第[一二三四五六七八九十\d]+[章节条]|^[一二三四五六七八九十]+[、\.])'), 2),
    (re.compile(r'(?:注[：:]|说明[：:]|注意[：:]|提示[：:]|附[：:])'), 1),
    (re.compile(r'(?:不得|必须|应当|严禁|禁止|须按|须在|应在)'), 1),
    (re.compile(r'(?:投标人须知|前附表|招标公告|资格要求|评审办法|投标须知)'), 2),
    (re.compile(r'(?:投诉|质疑|答复|行政复议|起[诉])'), 1),
]

# 变量内容语义特征
_VARIABLE_INDICATORS = [
    (re.compile(r'[（(][^）)]*(?:项目名称|采购人|招标人|投标人|金额|日期|编号|数量|填写)[^）)]*[）)]'), 4),
    (re.compile(r'(?:本项目|该工程|本工程|本次招标|本次采购).{0,15}(?:位于|地点|规模|内容|预算|投资)'), 3),
    (re.compile(r'(?:投标人|供应商).{0,5}(?:资格|资质|要求|条件|须|需|应)'), 2),
    (re.compile(r'(?:技术参数|技术要求|技术规格|性能指标|配置要求)'), 3),
    (re.compile(r'[（(][^）)]{0,30}[）)]'), 2),
    (re.compile(r'(?:业绩|案例|经验).{0,10}(?:要求|条件|需要|提供)'), 2),
    (re.compile(r'(?:评分|分值|权重|得分|满分|扣分)'), 2),
    (re.compile(r'(?:预算|最高限价|控制价|投标报价|价格)'), 2),
    (re.compile(r'(?:工期|交货期|服务期|工期要求|完成时间)'), 2),
    (re.compile(r'[Xx_＿]{2,}'), 3),
    (re.compile(r'□'), 2),
]


class HeuristicMarker:
    """启发性标记器：不依赖指纹库，基于语义特征判断"""

    def mark_section(self, section_text: str, section_type: str = "") -> list[TextSpan]:
        """对单个章节的文本进行定变分离标记"""
        sentences = _SENTENCE_SPLIT_RE.split(section_text)
        spans: list[TextSpan] = []

        for i, sent in enumerate(sentences):
            sent = sent.strip()
            if not sent:
                continue
            if len(sent) < 3:
                continue

            label, confidence = self._classify_sentence(sent, section_type)
            spans.append(TextSpan(
                text=sent,
                label=label,
                confidence=confidence,
                section_type=section_type,
            ))

        # ── 上下文平滑：相邻固定块中的短句 ──────────────────
        spans = self._context_smoothing(spans)

        return spans

    def _classify_sentence(self, text: str, section_type: str = "") -> tuple[str, float]:
        """基于语义特征对单句分类

        Returns:
            (label, confidence)
        """
        fixed_score = 0
        var_score = 0

        for pattern, weight in _FIXED_INDICATORS:
            if pattern.search(text):
                fixed_score += weight

        for pattern, weight in _VARIABLE_INDICATORS:
            if pattern.search(text):
                var_score += weight

        # 长句调整：超长固定文本更可能是模板
        if len(text) > 80 and fixed_score >= 3:
            fixed_score += 2

        # 短句调整
        if len(text) < 10 and var_score == 0:
            fixed_score += 1

        # 决定标签
        if var_score >= 4:
            return "VARIABLE", min(0.9, 0.6 + var_score * 0.08)
        elif fixed_score >= 5 and var_score <= 1:
            return "FIXED", min(0.9, 0.6 + fixed_score * 0.06)
        elif fixed_score >= 3 and var_score == 0:
            return "FIXED", 0.65
        elif var_score >= 2 and fixed_score <= 2:
            return "VARIABLE", 0.65
        else:
            return "UNCERTAIN", 0.5

    @staticmethod
    def _context_smoothing(spans: list[TextSpan]) -> list[TextSpan]:
        """上下文平滑：前后都是 FIXED 的短 UNCERTAIN 句 → 推断为 FIXED"""
        if len(spans) < 2:
            return spans

        for i in range(1, len(spans) - 1):
            if spans[i].label == "UNCERTAIN" and spans[i].length <= 15:
                if spans[i-1].label == "FIXED" and spans[i+1].label == "FIXED":
                    spans[i].label = "FIXED"
                    spans[i].confidence = 0.55  # 低置信度推断

        return spans


# ═══════════════════════════════════════════════════════════════
# 主标记器
# ═══════════════════════════════════════════════════════════════

class VariableMarker:
    """招标文件定变分离标记器

    两级策略：
    1. 有指纹库：精确哈希 + 模糊 n-gram 匹配
    2. 无指纹库：启发式语义特征判断
    """

    def __init__(self):
        self._heuristic = HeuristicMarker()
        self._db = None

    @property
    def fingerprint_db(self):
        """懒加载指纹库"""
        if self._db is None:
            try:
                from app.engine.template_fingerprint import get_fingerprint_db
                self._db = get_fingerprint_db()
            except ImportError:
                logger.info("指纹库模块不可用，使用启发式标记")
                self._db = None
            except Exception as e:
                logger.warning("指纹库加载失败: %s，使用启发式标记", e)
                self._db = None
        return self._db

    def mark(
        self,
        parsed_doc: ParsedDocument,
        sector: str = "",
        procurement_method: str = "",
        project_type: str = "",
    ) -> MarkedDocument:
        """对解析后的文档进行定变分离标记

        Args:
            parsed_doc: 解析器输出的结构化文档
            sector: 行业（政府采购/公路工程/水利工程/铁路工程）
            procurement_method: 采购方式
            project_type: 项目类型（货物类/服务类/工程类）

        Returns:
            MarkedDocument
        """
        marked = MarkedDocument(
            filename=parsed_doc.filename,
            full_text=parsed_doc.full_text,
            sector=sector,
            procurement_method=procurement_method,
            project_type=project_type,
        )

        db = self.fingerprint_db
        use_fingerprint = db is not None and db._loaded

        total_fixed = 0
        total_variable = 0
        total_uncertain = 0
        total_chars = 0

        for sec_type, sec_text in parsed_doc.sections.items():
            if use_fingerprint:
                spans = self._mark_with_fingerprint(
                    sec_text, sec_type, sector, procurement_method, project_type, db
                )
            else:
                spans = self._heuristic.mark_section(sec_text, sec_type)

            marked.sections[sec_type] = spans

            for span in spans:
                total_chars += span.length
                if span.label == "FIXED":
                    total_fixed += span.length
                elif span.label == "VARIABLE":
                    total_variable += span.length
                else:
                    total_uncertain += span.length

        # ── 统计 ────────────────────────────────────────────
        if total_chars > 0:
            marked.stats = {
                "fixed_ratio": round(total_fixed / total_chars, 3),
                "variable_ratio": round(total_variable / total_chars, 3),
                "uncertain_ratio": round(total_uncertain / total_chars, 3),
                "total_chars": total_chars,
                "sections_marked": len(marked.sections),
                "method": "fingerprint" if use_fingerprint else "heuristic",
            }

        logger.info(
            "定变分离完成: %s | fixed=%.1f%% variable=%.1f%% uncertain=%.1f%% [%s]",
            parsed_doc.filename,
            marked.stats.get("fixed_ratio", 0) * 100,
            marked.stats.get("variable_ratio", 0) * 100,
            marked.stats.get("uncertain_ratio", 0) * 100,
            marked.stats.get("method", "unknown"),
        )

        return marked

    def _mark_with_fingerprint(
        self,
        section_text: str,
        section_type: str,
        sector: str,
        procurement_method: str,
        project_type: str,
        db,
    ) -> list[TextSpan]:
        """基于指纹库的精确标记"""
        sentences = _SENTENCE_SPLIT_RE.split(section_text)
        spans: list[TextSpan] = []

        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 3:
                continue

            # 优先级 1: 占位符检测 → VARIABLE
            if db.is_variable_marker(sent):
                spans.append(TextSpan(
                    text=sent, label="VARIABLE", confidence=0.90,
                    section_type=section_type,
                ))
                continue

            # 优先级 2: 精确指纹匹配 → FIXED
            is_fixed, conf, fp_id = db.is_known_fixed(sent, fuzzy=False)
            if is_fixed:
                spans.append(TextSpan(
                    text=sent, label="FIXED", confidence=conf,
                    fingerprint_id=fp_id, section_type=section_type,
                ))
                continue

            # 优先级 3: 模糊指纹匹配 → FIXED
            is_fixed, conf, fp_id = db.is_known_fixed(sent, fuzzy=True)
            if is_fixed:
                spans.append(TextSpan(
                    text=sent, label="FIXED", confidence=conf,
                    fingerprint_id=fp_id, section_type=section_type,
                ))
                continue

            # 优先级 4: 启发式兜底
            label, conf = self._heuristic._classify_sentence(sent, section_type)
            spans.append(TextSpan(
                text=sent, label=label, confidence=conf,
                section_type=section_type,
            ))

        # ── 上下文平滑 ──────────────────────────────────────
        spans = self._heuristic._context_smoothing(spans)

        return spans

    def quick_check(self, text: str) -> tuple[str, float]:
        """快速判断单段文本的定变属性（用于 API 层的轻量级查询）

        Returns:
            (label, confidence)
        """
        db = self.fingerprint_db
        if db and db._loaded:
            # 占位符检测
            if db.is_variable_marker(text):
                return "VARIABLE", 0.90
            # 指纹匹配
            is_fixed, conf, _ = db.is_known_fixed(text, fuzzy=True)
            if is_fixed:
                return "FIXED", conf

        # 启发式兜底
        return self._heuristic._classify_sentence(text)


# ── 模块级单例 ──────────────────────────────────────────────

variable_marker = VariableMarker()


# ── 辅助导出 ───────────────────────────────────────────────

def build_marked_text_for_review(
    parsed_doc: ParsedDocument,
    sector: str = "",
    procurement_method: str = "",
    project_type: str = "",
) -> dict[str, str]:
    """便捷函数：构建适合审查引擎使用的标记文本

    返回两个版本的章节文本：
    - variable_only: 仅变量部分（用于规则引擎的禁用词/关键字检测）
    - marked_full: 完整文本带 <<TEMPLATE>>/<<REVIEW>> 标记（用于 LLM）
    """
    md = variable_marker.mark(parsed_doc, sector, procurement_method, project_type)

    variable_sections: dict[str, str] = {}
    marked_sections: dict[str, str] = {}

    for sec_type in parsed_doc.sections:
        variable_sections[sec_type] = md.get_variable_text(sec_type)
        marked_sections[sec_type] = md.get_text_for_llm(sec_type)

    return {
        "variable_only": variable_sections,
        "marked_full": marked_sections,
    }
