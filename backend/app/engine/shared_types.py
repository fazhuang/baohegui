"""
共享类型定义 —— 打破 llm_engine ↔ rule_engine 循环导入

这两个模块互相引用：
  - llm_engine._extract_violated_sections() 需要 Violation 类型
  - rule_engine 被 fusion 导入，而 fusion 被所有地方使用

解决：将 Violation 和 RuleEngineResult 两个核心类型提取到此独立模块，
让 llm_engine / fusion / api 等单位可以自由 import，不会形成循环依赖。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Violation(BaseModel):
    """一条违规记录（规则引擎输出）"""

    rule_id: str
    rule_type: str = Field(
        ...,
        pattern=r"^(chapter_required|keyword_required|forbidden|format_required)$",
    )
    description: str
    location: Optional[str] = None
    text: Optional[str] = None
    risk_level: str = "medium"
    suggestion: str = ""
    platform_codes: list[dict] = []
    law_ref: Optional[str] = None
    weight: float = 10.0
    # 定变分离标记字段
    span_label: str = ""                    # 违规所在文本段的标签: FIXED / VARIABLE / UNCERTAIN
    is_template_false_positive: bool = False  # 是否为模板固定内容误报
    template_confidence: float = 0.0         # 模板匹配的置信度


class RuleEngineResult(BaseModel):
    """规则引擎检查结果"""

    violations: list[Violation] = []
    section_score: float = 100.0
    keyword_score: float = 100.0
    forbidden_score: float = 100.0
    total_score: float = 100.0
