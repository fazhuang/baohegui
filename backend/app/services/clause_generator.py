"""智能合同条款生成服务

根据合规审查发现的问题和整改建议，调用 LLM 生成合规的替代条款。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import settings
from app.engine.llm_engine import llm_engine

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "rules" / "prompts"


class ClauseGenerator:
    """合同条款生成器"""

    def __init__(self):
        self._template: Optional[str] = None

    @property
    def template(self) -> str:
        """加载条款生成 Prompt 模板"""
        if self._template is None:
            prompt_path = _PROMPTS_DIR / "clause_generate.txt"
            if prompt_path.exists():
                self._template = prompt_path.read_text(encoding="utf-8")
            else:
                self._template = self._fallback_template()
        return self._template

    @staticmethod
    def _fallback_template() -> str:
        """兜底模板"""
        return """你是一个专业的政府采购合同条款撰写专家。
请根据以下违规原文和整改建议，生成合规的替代条款。

违规原文：{original_text}
整改建议：{suggestion}

生成1-2段合规替代条款，标注法律依据。
以JSON格式输出：[{{"clause_title":"...", "clause_text":"...", "law_ref":"...", "explanation":"..."}}]"""

    async def generate(
        self,
        original_text: str,
        rule_description: str,
        suggestion: str,
        project_type: str = "",
        budget: str = "",
        industry: str = "",
    ) -> dict:
        """
        生成合规替代条款。

        Args:
            original_text: 原始违规文本
            rule_description: 触发规则的描述
            suggestion: 整改建议
            project_type: 项目类型
            budget: 预算金额
            industry: 行业

        Returns:
            {"clauses": [...], "model_used": "...", "tokens_used": 0}
        """
        # 使用安全替换（避免 JSON 中的 {} 被 str.format 解析）
        prompt = self.template
        replacements = {
            "{original_text}": original_text,
            "{rule_description}": rule_description,
            "{suggestion}": suggestion,
            "{project_type}": project_type or "未指定",
            "{budget}": budget or "未指定",
            "{industry}": industry or "通用",
        }
        for key, value in replacements.items():
            prompt = prompt.replace(key, value)

        # Mock 模式
        if settings.llm_mock_mode:
            return {
                "clauses": [
                    {
                        "clause_title": "合规条款（Mock）",
                        "clause_text": f"根据{suggestion}的建议，已将原文'{original_text[:50]}...'替换为合规表述。",
                        "law_ref": rule_description,
                        "explanation": "此条款已去除排他性/倾向性表述，确保至少3家供应商可参与竞争",
                    }
                ],
                "model_used": "mock",
                "tokens_used": 0,
            }

        # 使用 LLM Engine 的 Provider 调用大模型
        provider = llm_engine._provider
        if provider is None:
            return {"error": "LLM Provider 未初始化", "clauses": []}

        try:
            timeout = httpx.Timeout(settings.llm_timeout, connect=15.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                content, usage = await provider.chat(
                    prompt,
                    client,
                    settings.llm_max_tokens,
                    settings.llm_temperature + 0.2,  # 条款生成可适当提高创造性
                )
                # 使用引擎内置的 JSON 提取工具
                from app.engine.llm_engine import _extract_json

                raw = _extract_json(content)
                if raw is None:
                    return {
                        "error": "LLM 返回非 JSON 格式",
                        "clauses": [],
                        "raw": content[:500],
                    }

                return {
                    "clauses": raw if isinstance(raw, list) else [raw],
                    "model_used": settings.llm_model,
                    "tokens_used": usage.get("total_tokens", 0),
                }
        except Exception as e:
            logger.error("条款生成失败: %s", e)
            return {"error": str(e), "clauses": []}


clause_generator = ClauseGenerator()
