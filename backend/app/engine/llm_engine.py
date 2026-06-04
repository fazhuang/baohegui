"""大模型语义审查引擎

支持三种 Provider：
  - openai_compatible : 通义千问 / DeepSeek 等 OpenAI 兼容 API
  - ollama            : 本地 Ollama 部署
  - mock              : 开发模式（内置模拟数据）

功能特性：
  - 从 rules/prompts/ 加载 Prompt 模板（支持章节级分段调用以控制 Token）
  - 自动 JSON 解析（含 Markdown 代码块降级提取）
  - 指数退避重试
  - Token 用量与成本追踪
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.prompt_manager import PromptManager, PromptNotFoundError
from app.services.usage_tracker import (
    LLMUsageTracker,
    UsageRecord,
    usage_tracker  as _global_tracker,
)

from app.engine.shared_types import Violation  # 从共享模块导入，避免循环依赖

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

class LLMViolation(BaseModel):
    """大模型发现的一条语义违规"""
    type: str = Field(
        ...,
        pattern=r"^(exclusivity|bias|hidden_barrier|ambiguity|high_risk)$",
        description="违例类型：排他性/倾向性/隐性壁垒/含糊性/高风险",
    )
    section: str = ""
    text: str = ""
    risk_level: str = Field(
        default="medium",
        pattern=r"^(high|medium|low)$",
    )
    reason: str = ""
    suggestion: str = ""
    law_ref: Optional[str] = None
    weight: float = 10.0


class LLMEngineResult(BaseModel):
    """语义引擎审查结果"""
    violations: list[LLMViolation] = []
    total_score: float = 100.0
    model_used: str = ""
    tokens_used: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    cost_yuan: float = 0.0
    sections_analyzed: int = 0            # 实际调 LLM 的章节数
    sections_skipped: int = 0             # 被抽样跳过的章节数
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _extract_json(text: str) -> Optional[list[dict]]:
    """
    从 LLM 响应中提取 JSON 数组（兼容 Markdown 代码块包裹等情况）。
    优先级：```json ... ```  >  ``` ... ```  > 裸 JSON 数组
    """
    # 尝试代码块包裹的 JSON
    for pattern in (
        r"```json\s*(\[.*?\])\s*```",
        r"```\s*(\[.*?\])\s*```",
    ):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试在文本中找到第一个 [ ... ] 结构
    m = re.search(r"(\[.*\])", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    return None


def _extract_violated_sections(
    violations: list[Violation],
    all_sections: set[str],
) -> set[str]:
    """
    从规则引擎的违规列表中提取"有问题的章节名"。

    提取策略：
    - forbidden 违规：location 格式为 "评审办法 ~第1行" → 取 "评审办法"
    - keyword_required 违规：location 格式为 "应在《资格要求》中" → 取 "资格要求"
    - chapter_required 违规：章节本身缺失，不纳入（LLM 无法分析不存在的章节）

    Args:
        violations: 规则引擎输出的 Violation 列表
        all_sections: 文档中实际存在的所有章节名

    Returns:
        有违规的章节名集合（只包含 all_sections 中存在的章节）
    """
    section_pat = re.compile(r"《([^》]+)》")
    location_pat = re.compile(r"^(.+?)[\s~]")

    result: set[str] = set()
    for v in violations:
        if v.rule_type == "chapter_required":
            continue  # 缺失章节无需 LLM 分析

        name: Optional[str] = None
        if v.location:
            # "应在《资格要求》中" → "资格要求"
            m = section_pat.search(v.location)
            if m:
                name = m.group(1)
            else:
                # "评审办法 ~第1行" → "评审办法"
                m = location_pat.match(v.location)
                if m:
                    name = m.group(1).strip()

        if name and name in all_sections:
            result.add(name)

    return result


def _build_section_prompt(
    sections: dict[str, str],
    prompt_template: str,
    token_limit: int,
    violated_sections: set[str] | None = None,
    sampling_rate: float = 0.3,
    marked_doc: Any | None = None,
) -> tuple[list[dict[str, str]], int]:
    """
    将文档章节智能分批，送入大模型分析。

    分批策略（成本优化）：
    - 规则引擎已查出违规的章节 → 100% 送入
    - 规则引擎未查出违规的章节 → 按 sampling_rate 概率抽样
      抽样基于章节名的 hash，保证同一文档多次分析结果一致

    定变分离优化：
    - 提供 marked_doc 时，使用标记文本（<<TEMPLATE>> / <<REVIEW>> 标记）
    - LLM 会被告知：<<TEMPLATE>> 区域为标准模板固定文字，无需审查
    - <<REVIEW>> 区域才是代理机构填写的变量内容，是审查重点

    Args:
        sections:         章节名 → 内容
        prompt_template:  Prompt 模板（含 {text} 占位符）
        token_limit:      每批 Token 上限
        violated_sections: 规则引擎已查出违规的章节名集合
        sampling_rate:    无违规章节的抽样比例 (0~1)，默认 0.3
        marked_doc:       定变分离标记后的文档（可选）

    Returns:
        (chunks, sections_skipped)
        chunks: [{"section_name": ..., "prompt": ...}, ...]
        sections_skipped: 被抽样跳过的章节数
    """
    violated_sections = violated_sections or set()
    chunks: list[dict[str, str]] = []
    current_chunk: list[str] = []
    current_size = 0
    sections_skipped = 0

    # 粗略估计：1 个汉字 ≈ 2 tokens
    EST_TOKENS_PER_CHAR = 2

    for sec_name, sec_content in sections.items():
        # ── 成本优化：判断是否跳过 ──────────────────────────
        is_violated = sec_name in violated_sections
        if not is_violated:
            # 基于章节名 hash 确定是否抽样——确定性的，保证可复现
            seed = hash(sec_name) & 0x7FFFFFFF
            if (seed % 1000) / 1000.0 > sampling_rate:
                sections_skipped += 1
                logger.debug(
                    "跳过章节 [%s]（规则引擎无违规，抽样 %.0f%% 未命中）",
                    sec_name, sampling_rate * 100,
                )
                continue

        # ── 定变分离：获取标记文本 ─────────────────────────
        if marked_doc and hasattr(marked_doc, 'get_text_for_llm'):
            # 使用标记过的文本（<<TEMPLATE>> / <<REVIEW>> 分隔）
            marked_text = marked_doc.get_text_for_llm(sec_name)
            if marked_text.strip():
                text_block = f"{marked_text}\n\n"
            else:
                text_block = f"=== {sec_name} ===\n{sec_content}\n\n"
        else:
            text_block = f"=== {sec_name} ===\n{sec_content}\n\n"

        block_tokens = len(text_block) * EST_TOKENS_PER_CHAR

        tag = "🔍 必检" if is_violated else "📊 抽检"
        logger.debug(
            "%s 章节 [%s] (~%d tokens)", tag, sec_name, block_tokens,
        )

        if current_size + block_tokens > token_limit and current_chunk:
            # flush 当前批
            combined = "".join(current_chunk)
            chunks.append({
                "section_name": " + ".join(
                    c.split("\n")[0].replace("=== ", "").replace(" ===", "")
                    for c in current_chunk
                ),
                "prompt": prompt_template.replace("{text}", combined),
            })
            current_chunk = [text_block]
            current_size = block_tokens
        else:
            current_chunk.append(text_block)
            current_size += block_tokens

    # 最后一批
    if current_chunk:
        combined = "".join(current_chunk)
        chunks.append({
            "section_name": " + ".join(
                c.split("\n")[0].replace("=== ", "").replace(" ===", "")
                for c in current_chunk
            ),
            "prompt": prompt_template.replace("{text}", combined),
        })

    return chunks, sections_skipped


# ═══════════════════════════════════════════════════════════════
# Provider 实现
# ═══════════════════════════════════════════════════════════════

class BaseProvider:
    """Provider 基类"""

    def __init__(self, api_base: str, api_key: str, model: str):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def chat(
        self,
        prompt: str,
        client: httpx.AsyncClient,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, dict]:
        """调用 LLM 并返回 (content_text, usage_dict)"""
        raise NotImplementedError


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI 兼容格式（Qwen / DeepSeek / 智谱等）"""

    async def chat(
        self,
        prompt: str,
        client: httpx.AsyncClient,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, dict]:
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return content, usage


class OllamaProvider(BaseProvider):
    """Ollama 原生 API（非 OpenAI 兼容模式）"""

    async def chat(
        self,
        prompt: str,
        client: httpx.AsyncClient,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, dict]:
        # Ollama chat API: POST /api/chat
        base = self.api_base
        # 自动处理 /v1 后缀（Ollama 两种接口共存）
        if base.endswith("/v1"):
            base = base[:-3]
        url = f"{base}/api/chat"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
            "stream": False,
        }

        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        content = data["message"]["content"]
        # Ollama 返回 eval_count 而非 OpenAI 格式的 usage
        usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
            "total_tokens": (data.get("prompt_eval_count", 0)
                             + data.get("eval_count", 0)),
        }
        return content, usage


# ═══════════════════════════════════════════════════════════════
# 引擎主类
# ═══════════════════════════════════════════════════════════════

PROVIDER_COST_ESTIMATES: dict[str, tuple[float, float]] = {
    # (input_cost_per_1k, output_cost_per_1k) 单位：元
    "qwen-turbo":       (0.0008, 0.002),
    "qwen-plus":        (0.002,  0.006),
    "qwen-max":         (0.004,  0.012),
    "deepseek-chat":    (0.001,  0.002),
    "deepseek-reasoner":(0.004,  0.016),
    "glm-4-plus":       (0.005,  0.005),
}


class LLMEngine:
    """大模型语义审查引擎"""

    # ── 初始化 ──────────────────────────────────────────────

    def __init__(self):
        self.mock_mode = settings.llm_mock_mode
        self.provider_name = settings.llm_provider
        self.api_base = settings.llm_api_base
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self.max_tokens = settings.llm_max_tokens
        self.temperature = settings.llm_temperature
        self.timeout = settings.llm_timeout
        self.retry_count = settings.llm_retry_count
        self.retry_delay = settings.llm_retry_delay
        self.token_limit = settings.llm_token_limit_per_call
        self.cost_per_1k_input = settings.llm_cost_per_1k_input
        self.cost_per_1k_output = settings.llm_cost_per_1k_output

        # 创建 PromptManager（热加载就绪）
        self.prompt_manager = PromptManager()
        self._prompt_template: Optional[str] = None  # 懒加载缓存

        # 创建 Provider
        self._provider: Optional[BaseProvider] = None
        if not self.mock_mode:
            self._provider = self._build_provider()

        # 调用追踪
        self.usage_tracker = _global_tracker

    @property
    def prompt_template(self) -> str:
        """懒加载默认 Prompt 模板（compliance_check 最新版）"""
        if self._prompt_template is None:
            try:
                tmpl = self.prompt_manager.get_prompt("compliance_check")
                self._prompt_template = tmpl.content
                logger.info(
                    "加载 Prompt 模板: %s v%d (%s)",
                    tmpl.name, tmpl.version, tmpl.path,
                )
            except PromptNotFoundError:
                logger.warning("Prompt 模板未找到，使用内置默认模板")
                self._prompt_template = self._fallback_prompt()
        return self._prompt_template

    @staticmethod
    def _fallback_prompt() -> str:
        """内置兜底 Prompt（磁盘上无模板时使用）"""
        return """你是一个专业的政府采购合规审查专家。请审查以下招标文件片段，判断是否存在合规风险。

审查维度：
1. 排他性条款（exclusivity）：是否通过不合理的技术参数、业绩要求、注册地等设定排他性条件
2. 倾向性评分（bias）：评分标准是否明显偏向特定供应商或产品
3. 隐性壁垒（hidden_barrier）：是否存在表面合规但实际设置不合理门槛的条款
4. 质疑风险（high_risk）：哪些条款最容易引发供应商质疑或投诉
5. 条款含糊性（ambiguity）：是否存在表述模糊、存在歧义的条款

招标文件片段：
{text}

请以 JSON 格式输出审查结果，不要包含其他内容：
[
  {
    "type": "exclusivity|bias|hidden_barrier|ambiguity|high_risk",
    "section": "所在章节名称",
    "text": "涉嫌违规的原文片段",
    "risk_level": "high|medium|low",
    "reason": "判断理由（引用相关法规）",
    "suggestion": "整改建议",
    "law_ref": "引用的法规条文"
  }
]"""

    # ── Provider 工厂 ───────────────────────────────────────

    def _build_provider(self) -> BaseProvider:
        provider_map: dict[str, type[BaseProvider]] = {
            "openai_compatible": OpenAICompatibleProvider,
            "ollama": OllamaProvider,
        }
        cls = provider_map.get(self.provider_name)
        if not cls:
            logger.warning(
                "未知 Provider '%s'，回退到 openai_compatible",
                self.provider_name,
            )
            cls = OpenAICompatibleProvider
        return cls(self.api_base, self.api_key, self.model)

    # ── 核心审查方法 ────────────────────────────────────────

    async def analyze(
        self,
        sections: dict[str, str],
        rule_violations: list[Violation] | None = None,
        file_id: Optional[int] = None,
        user_id: Optional[int] = None,
        target_section_types: set[str] | None = None,
        marked_doc: Any | None = None,
    ) -> LLMEngineResult:
        """
        对结构化文档进行语义合规审查。

        成本优化策略（接收规则引擎结果时生效）：
        - 规则引擎已查出违规的章节 → 100% 送入 LLM
        - 规则引擎未查出违规的章节 → 按 30% 概率抽样检查
        - 缺失的章节 → 不检查（LLM 无法分析不存在的内容）

        定变分离优化：
        - 提供 marked_doc 时，LLM 收到标记文本（<<TEMPLATE>> / <<REVIEW>>）
        - LLM 被明确指令：忽略 <<TEMPLATE>> 中的固定模板文字

        Args:
            sections:        解析器输出的结构化章节
            rule_violations: 规则引擎的违规结果（用于成本优化）
            file_id:         关联的文件 ID（用于用量追踪）
            user_id:         关联的用户 ID（用于用量追踪）
            target_section_types: 目标章节类型集合
            marked_doc:      定变分离标记后的文档（可选）
        """
        if self.mock_mode:
            return self._mock_analyze(sections, marked_doc=marked_doc)

        if self._provider is None:
            return LLMEngineResult(error="Provider 未初始化")

        # ── 确定必须检查的章节 ──────────────────────────────
        all_section_names = set(sections.keys())
        violated_sections: set[str] = set()

        # 如果指定了目标章节类型，只处理这些章节（用于精准语义分析）
        if target_section_types:
            sections = {
                k: v for k, v in sections.items()
                if k in target_section_types
            }
            if not sections:
                logger.info("目标章节类型 %s 均未在文档中找到，跳过 LLM 分析", target_section_types)
                return LLMEngineResult(
                    model_used=self.model,
                    sections_analyzed=0,
                    sections_skipped=0,
                )
        if rule_violations:
            violated_sections = _extract_violated_sections(
                rule_violations, all_section_names,
            )
            n_violated = len(violated_sections)
            n_clean = len(all_section_names) - n_violated
            logger.info(
                "成本优化: %d 个章节有规则违规(100%%必检), "
                "%d 个章节无违规(30%%抽样)",
                n_violated, n_clean,
            )

        # ── 构建 Prompt 分片 ────────────────────────────────
        chunks, sections_skipped = _build_section_prompt(
            sections=sections,
            prompt_template=self.prompt_template,
            token_limit=self.token_limit,
            violated_sections=violated_sections,
            sampling_rate=0.3,
            marked_doc=marked_doc,
        )
        if not chunks:
            logger.info("所有章节均被抽样跳过，无需 LLM 调用")
            return LLMEngineResult(
                model_used=self.model,
                sections_analyzed=0,
                sections_skipped=sections_skipped,
            )

        all_violations: list[LLMViolation] = []
        total_input_tokens = 0
        total_output_tokens = 0
        sections_ok = 0
        last_error: Optional[str] = None

        timeout_cfg = httpx.Timeout(self.timeout, connect=15.0)
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)

        async with httpx.AsyncClient(timeout=timeout_cfg, limits=limits) as client:
            for chunk in chunks:
                t_start = time.monotonic()
                violations, usage, err = await self._call_with_retry(
                    client, chunk["prompt"],
                )
                duration = time.monotonic() - t_start

                pt = usage.get("prompt_tokens", 0)
                ct = usage.get("completion_tokens", 0)
                total_input_tokens += pt
                total_output_tokens += ct

                # ── 记录用量 ─────────────────────────────────
                if not self.mock_mode:
                    chunk_cost = self._calc_cost(pt, ct)
                    self.usage_tracker.record_call(
                        model=self.model,
                        provider=self.provider_name,
                        prompt_tokens=pt,
                        completion_tokens=ct,
                        duration_seconds=duration,
                        cost_yuan=chunk_cost,
                        success=(err is None),
                        error_message=err or "",
                        file_id=file_id,
                        user_id=user_id,
                        section_name=chunk["section_name"],
                        prompt_length=len(chunk["prompt"]),
                    )

                if violations:
                    for v in violations:
                        if not v.section:
                            v.section = chunk["section_name"]
                    all_violations.extend(violations)
                    sections_ok += 1
                elif err:
                    last_error = err
                    logger.warning(
                        "章节 [%s] 审查失败: %s", chunk["section_name"], err,
                    )
                else:
                    sections_ok += 1  # 无违规也是成功

        total_tokens = total_input_tokens + total_output_tokens

        # 计算成本
        cost = self._calc_cost(total_input_tokens, total_output_tokens)

        # 综合评分
        total_deduction = sum(v.weight for v in all_violations)
        total_score = max(0.0, 100.0 - total_deduction)

        return LLMEngineResult(
            violations=all_violations,
            total_score=round(total_score, 1),
            model_used=self.model,
            tokens_used=total_tokens,
            tokens_input=total_input_tokens,
            tokens_output=total_output_tokens,
            cost_yuan=round(cost, 4),
            sections_analyzed=sections_ok,
            sections_skipped=sections_skipped,
            error=last_error,
        )

    # ── 单次调用（含重试） ─────────────────────────────────

    async def _call_with_retry(
        self,
        client: httpx.AsyncClient,
        prompt: str,
    ) -> tuple[list[LLMViolation], dict, Optional[str]]:
        """
        调用 LLM 并解析结果，失败时指数退避重试。
        返回 (violations, usage_dict, error_message)
        """
        last_error: Optional[str] = None

        for attempt in range(1, self.retry_count + 2):  # 1 + retry_count 次
            try:
                content, usage = await self._provider.chat(
                    prompt, client, self.max_tokens, self.temperature,
                )

                # 解析 JSON
                raw = _extract_json(content)
                if raw is None:
                    raise ValueError(
                        f"LLM 返回非 JSON 格式: {content[:200]}..."
                    )

                violations = [LLMViolation(**v) for v in raw]
                return violations, usage, None

            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}"
                logger.warning(
                    "LLM 调用失败 (attempt %d/%d): %s",
                    attempt, self.retry_count + 1, last_error,
                )
            except httpx.TimeoutException:
                last_error = "超时"
                logger.warning(
                    "LLM 超时 (attempt %d/%d)",
                    attempt, self.retry_count + 1,
                )
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                last_error = str(e)
                logger.warning(
                    "LLM 响应解析失败 (attempt %d/%d): %s",
                    attempt, self.retry_count + 1, last_error,
                )
                # 解析错误不重试——模型能返回 JSON 但格式不对，重试一般无用
                return [], {}, last_error
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.error(
                    "LLM 未知错误 (attempt %d/%d): %s",
                    attempt, self.retry_count + 1, last_error,
                )

            if attempt <= self.retry_count:
                delay = self.retry_delay * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

        return [], {}, last_error

    # ── 成本计算 ────────────────────────────────────────────

    def _calc_cost(self, input_tokens: int, output_tokens: int) -> float:
        """根据模型已知定价或用户配置估算成本"""
        # 优先用用户配置的单价
        if self.cost_per_1k_input > 0 or self.cost_per_1k_output > 0:
            return (
                input_tokens / 1000 * self.cost_per_1k_input
                + output_tokens / 1000 * self.cost_per_1k_output
            )

        # 否则按模型名查内置定价表
        for model_prefix, (in_cost, out_cost) in PROVIDER_COST_ESTIMATES.items():
            if self.model.startswith(model_prefix):
                return (
                    input_tokens / 1000 * in_cost
                    + output_tokens / 1000 * out_cost
                )

        return 0.0

    # ── Mock 模式 ───────────────────────────────────────────

    def _mock_analyze(
        self,
        sections: dict[str, str],
        marked_doc: Any | None = None,
    ) -> LLMEngineResult:
        """
        Mock 模式：返回预设的审查结果。
        支持从 sections 中检测关键词后生成对应违例。

        定变分离优化：
        - 指纹库模式：只在 VARIABLE 和 UNCERTAIN 标记的文本中检测，跳过 FIXED
        - 启发式模式：使用原始章节文本，避免标记不可靠导致漏检
        """
        violations: list[LLMViolation] = []

        # ── 判断标记方法的可靠性 ──────────────────────────────
        is_fingerprint_mode = (
            marked_doc is not None
            and hasattr(marked_doc, 'stats')
            and marked_doc.stats.get("method") == "fingerprint"
        )

        # ── 获取每个章节需要检查的文本 ────────
        def _check_text(sec_name: str, sec_text: str) -> str:
            """返回该章节需要检查的文本"""
            if is_fingerprint_mode and marked_doc and hasattr(marked_doc, 'get_variable_text'):
                variable_text = marked_doc.get_variable_text(sec_name)
                # 如果变量文本为空，回退到原始文本
                return variable_text if variable_text.strip() else sec_text
            return sec_text

        # 预设的检测规则
        mock_checks: list[dict[str, Any]] = [
            {
                "keywords": ["本地企业", "本地注册", "本市"],
                "violation": LLMViolation(
                    type="exclusivity",
                    text="要求投标人必须为本市注册企业",
                    risk_level="high",
                    reason="根据《政府采购法》第五条，不得以注册地条件对供应商实行差别待遇",
                    suggestion="删除'本市注册'要求，改为全国范围内的符合资质供应商均可参与",
                    law_ref="《政府采购法》第五条",
                    weight=20,
                ),
            },
            {
                "keywords": ["指定品牌", "指定型号", "唯一"],
                "violation": LLMViolation(
                    type="exclusivity",
                    text="指定使用XX品牌产品",
                    risk_level="high",
                    reason="指定品牌违反《政府采购法》第二十二条，属于排他性条款",
                    suggestion="改为'或同等性能产品'，并提供技术参数要求",
                    law_ref="《政府采购法》第二十二条",
                    weight=20,
                ),
            },
            {
                "keywords": ["倾向", "明显偏高", "不合理权重", "特定"],
                "violation": LLMViolation(
                    type="bias",
                    text="评分标准中设置了明显偏向特定供应商的指标",
                    risk_level="medium",
                    reason="评分标准可能存在倾向性",
                    suggestion="重新评估各评分项的权重分配，确保公平公正",
                    weight=10,
                ),
            },
            {
                "keywords": ["注册资金", "注册资本"],
                "violation": LLMViolation(
                    type="hidden_barrier",
                    text="以注册资金作为资格门槛",
                    risk_level="medium",
                    reason="注册资金与履约能力无必然关联，属于隐性壁垒",
                    suggestion="删除注册资金要求，改用项目履约能力相关的资格条件",
                    law_ref="《政府采购法实施条例》第二十条",
                    weight=15,
                ),
            },
            {
                "keywords": ["仅限", "仅有", "只能"],
                "violation": LLMViolation(
                    type="exclusivity",
                    text="条款中使用'仅限'限制了供应商范围",
                    risk_level="high",
                    reason="使用'仅限'属于排他性表述",
                    suggestion="删除排他性限定词，改为开放性的资格要求",
                    weight=20,
                ),
            },
            {
                "keywords": ["酌情", "视情况", "等"],
                "violation": LLMViolation(
                    type="ambiguity",
                    text="条款中存在模糊表述",
                    risk_level="low",
                    reason="'酌情'等表述存在歧义，容易引发质疑",
                    suggestion="明确具体标准和条件，避免模糊措辞",
                    weight=5,
                ),
            },
        ]

        for sec_name, sec_text in sections.items():
            check_text = _check_text(sec_name, sec_text)
            for check in mock_checks:
                for kw in check["keywords"]:
                    if kw in check_text:
                        v = check["violation"].model_copy()
                        v.section = sec_name
                        # 原文摘取（从原始 sec_text 摘取，保持可读性）
                        idx = sec_text.find(kw)
                        if idx >= 0:
                            v.text = sec_text[max(0, idx - 15):idx + 30].strip()
                        violations.append(v)
                        break

        total_deduction = sum(v.weight for v in violations)
        return LLMEngineResult(
            violations=violations,
            total_score=max(0.0, 100.0 - total_deduction),
            model_used="mock",
        )


# 模块级单例
llm_engine = LLMEngine()
