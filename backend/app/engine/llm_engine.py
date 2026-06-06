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
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.engine.shared_types import Violation  # 从共享模块导入，避免循环依赖
from app.services.prompt_manager import PromptManager, PromptNotFoundError
from app.services.usage_tracker import (
    usage_tracker as _global_tracker,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# JSON Schema — LLM 输出结构定义
# ═══════════════════════════════════════════════════════════════

LLM_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["violations"],
    "properties": {
        "violations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "text", "risk_level", "reason", "confidence"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "exclusivity", "bias", "hidden_barrier",
                            "ambiguity", "high_risk", "format_issue",
                            "legal_risk", "procedural_issue"
                        ]
                    },
                    "section": {"type": "string"},
                    "text": {"type": "string"},
                    "risk_level": {"type": "string", "enum": ["high", "medium", "low"]},
                    "reason": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "evidence": {"type": "string"},
                    "law_ref": {"type": "string"},
                    "consequence": {"type": "string"},
                    "law_refs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "article": {"type": "string"}
                            }
                        }
                    }
                }
            }
        }
    }
}

# 从 schema 中提取的可接受值集合（供 _validate_schema / _parse_violations 使用）
_ALLOWED_VIOLATION_TYPES: set[str] = set(
    LLM_OUTPUT_SCHEMA["properties"]["violations"]["items"]["properties"]["type"]["enum"]
)
_ALLOWED_RISK_LEVELS: set[str] = set(
    LLM_OUTPUT_SCHEMA["properties"]["violations"]["items"]["properties"]["risk_level"]["enum"]
)


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════


class LLMViolation(BaseModel):
    """大模型发现的一条语义违规

    三段式可解释性字段（v3 新增）：
    - evidence:    风险事实 — 从文档中逐字引用的原文证据
    - consequence: 风险推演 — 若不修正的具体后果
    - confidence:  置信度评分 0.0-1.0
    """

    type: str = Field(
        ...,
        pattern=r"^(exclusivity|bias|hidden_barrier|ambiguity|high_risk|format_issue|legal_risk|procedural_issue)$",
        description="违例类型：排他性/倾向性/隐性壁垒/含糊性/高风险/格式问题/法律条款/程序问题",
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
    # ── 三段式可解释性（v3 新增） ─────────────────────────
    evidence: str = ""  # 风险事实：从文档逐字引用的原文
    consequence: str = ""  # 风险推演：若不修正的具体后果
    confidence: float = 0.0  # 置信度评分 (0.0-1.0)


class LLMEngineResult(BaseModel):
    """语义引擎审查结果"""

    violations: list[LLMViolation] = []
    total_score: float = 100.0
    model_used: str = ""
    tokens_used: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    cost_yuan: float = 0.0
    sections_analyzed: int = 0  # 实际调 LLM 的章节数
    sections_skipped: int = 0  # 被抽样跳过的章节数
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════
# 多模型路由
# ═══════════════════════════════════════════════════════════════


class ModelRouter:
    """多模型路由器

    加载 model_routing.json，将审查维度（如 AI-BRAND）映射到最优模型配置。

    用法::

        router = ModelRouter("rules/prompts/model_routing.json")
        config = router.route("AI-BRAND")
        # → {"provider": "openai_compatible", "api_base": "https://...", ...}
    """

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.default_model: str = "deepseek-chat"
        self.dimension_routing: dict[str, str] = {}
        self.model_configs: dict[str, dict] = {}
        self._load_config()

    def _load_config(self) -> None:
        """加载并解析模型路由配置文件"""
        # 支持相对于项目根、backend/ 目录的路径解析
        resolved = self._resolve_path(self.config_path)
        if not resolved or not resolved.exists():
            logger.warning(
                "模型路由配置文件不存在: %s，使用空路由表", self.config_path
            )
            return

        try:
            data = json.loads(resolved.read_text(encoding="utf-8"))
            self.default_model = data.get("default_model", "deepseek-chat")
            self.dimension_routing = data.get("dimension_routing", {})
            self.model_configs = data.get("model_configs", {})
            logger.info(
                "ModelRouter 加载完成: %d 维路由, %d 模型配置, 默认=%s",
                len(self.dimension_routing),
                len(self.model_configs),
                self.default_model,
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.error("模型路由配置解析失败: %s", e)
            # 保持空路由表，不会崩溃——route() 会 fall back 到默认

    @staticmethod
    def _resolve_path(config_path: str) -> Path | None:
        """解析配置文件路径，支持多种相对路径基准"""
        candidates = [
            lambda: Path(config_path),  # 直接路径 / 相对于 cwd
            lambda: Path(__file__).resolve().parent.parent.parent.parent / config_path,
            lambda: Path("backend") / config_path,
        ]
        for factory in candidates:
            try:
                p = factory()
                if p.exists():
                    return p
            except Exception:
                continue

        # 最后一个存在则返回（哪怕不存在），让调用方自行处理
        try:
            return candidates[1]()
        except Exception:
            return None

    def route(self, dimension_id: str) -> dict:
        """获取指定维度的模型配置

        Args:
            dimension_id: 审查维度 ID，如 "AI-BRAND"、"AI-STD"

        Returns:
            模型配置 dict，包含 provider / api_base / model 等字段。
            如果维度未在路由表中，fall back 到默认模型配置。
            如果对应模型配置也不存在，返回兜底配置。
        """
        model_name = self.dimension_routing.get(dimension_id, self.default_model)
        config = self.model_configs.get(model_name)

        if config:
            return config

        # 终极兜底：构造一个 openai_compatible 配置
        logger.warning(
            "维度 %s 的模型 %s 无配置，使用兜底默认", dimension_id, model_name
        )
        return {
            "provider": "openai_compatible",
            "api_base": settings.llm_api_base,
            "api_key_env": "",
            "model": model_name,
            "max_tokens": 4096,
            "temperature": 0.1,
            "cost_per_1k_input": 0.001,
            "cost_per_1k_output": 0.002,
        }

    def get_api_key(self, config: dict) -> str:
        """从模型配置中解析 API 密钥

        优先级：config.api_key_env → settings 对应字段 → 默认空
        """
        env_var = config.get("api_key_env", "")
        if env_var:
            key = os.environ.get(env_var, "")
            if key:
                return key
            # 尝试从 settings 获取
            settings_attr = f"llm_{env_var.lower()}"
            val = getattr(settings, settings_attr, "")
            if val:
                return val

        return ""


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
    est_tokens_per_char = 2

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
                    sec_name,
                    sampling_rate * 100,
                )
                continue

        # ── 定变分离：获取标记文本 ─────────────────────────
        if marked_doc and hasattr(marked_doc, "get_text_for_llm"):
            # 使用标记过的文本（<<TEMPLATE>> / <<REVIEW>> 分隔）
            marked_text = marked_doc.get_text_for_llm(sec_name)
            if marked_text.strip():
                text_block = f"{marked_text}\n\n"
            else:
                text_block = f"=== {sec_name} ===\n{sec_content}\n\n"
        else:
            text_block = f"=== {sec_name} ===\n{sec_content}\n\n"

        block_tokens = len(text_block) * est_tokens_per_char

        tag = "🔍 必检" if is_violated else "📊 抽检"
        logger.debug(
            "%s 章节 [%s] (~%d tokens)",
            tag,
            sec_name,
            block_tokens,
        )

        # ── 大章节拆分：防 413 ────────────────────────────────
        if block_tokens > token_limit:
            char_limit = token_limit // 2
            text = text_block
            for i in range(0, len(text), char_limit):
                part = text[i : i + char_limit]
                pname = f"{sec_name}({i // char_limit + 1})"
                part_block = f"=== {pname} ===\n{part}\n\n"
                pt = len(part_block) * 2
                if current_size + pt > token_limit and current_chunk:
                    combined = "".join(current_chunk)
                    chunks.append(
                        {
                            "section_name": " + ".join(
                                c.split("\n")[0].replace("=== ", "").replace(" ===", "")
                                for c in current_chunk
                            ),
                            "prompt": prompt_template.replace("{text}", combined),
                        }
                    )
                    current_chunk = []
                    current_size = 0
                current_chunk.append(part_block)
                current_size += pt
            continue

        if current_size + block_tokens > token_limit and current_chunk:
            # flush 当前批
            combined = "".join(current_chunk)
            chunks.append(
                {
                    "section_name": " + ".join(
                        c.split("\n")[0].replace("=== ", "").replace(" ===", "")
                        for c in current_chunk
                    ),
                    "prompt": prompt_template.replace("{text}", combined),
                }
            )
            current_chunk = [text_block]
            current_size = block_tokens
        else:
            current_chunk.append(text_block)
            current_size += block_tokens

    # 最后一批
    if current_chunk:
        combined = "".join(current_chunk)
        chunks.append(
            {
                "section_name": " + ".join(
                    c.split("\n")[0].replace("=== ", "").replace(" ===", "") for c in current_chunk
                ),
                "prompt": prompt_template.replace("{text}", combined),
            }
        )

    return chunks, sections_skipped


def _validate_schema(violations: list[dict]) -> list[dict]:
    """
    手动验证每条违规记录是否符合 LLM_OUTPUT_SCHEMA 定义的结构。

    验证规则：
    1. 必须是 dict
    2. 必须包含 type 字段且值在可接受枚举中
    3. 必须包含 text 字段（非空字符串）

    注意：confidence / risk_level / reason 等字段的缺失和无效值
    由 _parse_violations 负责填充默认值，不在此处丢弃。

    返回通过验证的违规记录列表（浅拷贝）。
    对验证失败的记录记录警告日志并丢弃。
    """
    valid: list[dict] = []

    for i, item in enumerate(violations):
        if not isinstance(item, dict):
            logger.warning("_validate_schema: item[%d] 不是 dict（类型=%s），丢弃", i, type(item).__name__)
            continue

        # ── 校验 type 字段存在且合法 ──────────────────────────
        item_type = item.get("type")
        if not isinstance(item_type, str) or item_type not in _ALLOWED_VIOLATION_TYPES:
            logger.warning(
                "_validate_schema: item[%d] type=%r 不在可接受枚举中，丢弃",
                i,
                item_type,
            )
            continue

        # ── 校验 text 字段存在 ────────────────────────────────
        item_text = item.get("text")
        if not item_text or not isinstance(item_text, str):
            logger.warning(
                "_validate_schema: item[%d] text 缺失或非字符串，丢弃",
                i,
            )
            continue

        valid.append(item)

    dropped = len(violations) - len(valid)
    if dropped:
        logger.info(
            "_validate_schema: %d/%d 条违规通过 schema 校验，%d 条被丢弃",
            len(valid),
            len(violations),
            dropped,
        )

    return valid


def _parse_violations(raw: list[dict]) -> list[LLMViolation]:
    """
    将 LLM JSON 响应解析为 LLMViolation 列表。

    增强处理流程：
    1. Schema 验证（_validate_schema），丢弃不合规的违规记录
    2. 字段别名映射（evidence_text → evidence, basis → law_ref）
    3. confidence 强制转换为 float 并 clamp 到 [0.0, 1.0]
    4. risk_level 缺失或无效时默认为 "medium"
    5. type 归一化到允许的枚举值（不在枚举中的记录已在 _validate_schema 阶段丢弃）

    支持三种输出格式：
    1. v2 格式（兼容）：type, section, text, risk_level, reason, suggestion, law_ref
    2. v3 格式（新增）：额外包含 evidence, consequence, confidence
    3. law_refs 格式：结构化法规引用列表
    """
    # ── Step 1: Schema 验证 ─────────────────────────────────
    validated = _validate_schema(raw)

    violations: list[LLMViolation] = []

    # 字段别名映射：LLM JSON key → LLMViolation field
    _FIELD_ALIASES: dict[str, str] = {
        "evidence_text": "evidence",
        "basis": "law_ref",
    }

    for i, item in enumerate(validated):
        # ── Step 2: 应用字段别名 ───────────────────────────────
        for alias, target in _FIELD_ALIASES.items():
            if alias in item and target not in item:
                item[target] = item.pop(alias)

        # ── Step 3: confidence 强制转为 float 并 clamp ─────────
        if "confidence" in item:
            try:
                item["confidence"] = float(item["confidence"])
            except (TypeError, ValueError):
                item["confidence"] = 0.5  # 默认值
            # Clamp 到 [0.0, 1.0]
            if item["confidence"] > 1.0:
                logger.warning(
                    "_parse_violations: item[%d] confidence=%.2f 超过上限，clamp 到 1.0",
                    i,
                    item["confidence"],
                )
                item["confidence"] = 1.0
            elif item["confidence"] < 0.0:
                logger.warning(
                    "_parse_violations: item[%d] confidence=%.2f 低于下限，clamp 到 0.0",
                    i,
                    item["confidence"],
                )
                item["confidence"] = 0.0
        else:
            # confidence 缺失时提供默认值
            item["confidence"] = 0.5

        # ── Step 4: risk_level 缺失或无效时默认 "medium" ────────
        if "risk_level" in item:
            if item["risk_level"] not in _ALLOWED_RISK_LEVELS:
                logger.warning(
                    "_parse_violations: item[%d] risk_level=%r 无效，默认设为 'medium'",
                    i,
                    item["risk_level"],
                )
                item["risk_level"] = "medium"
        else:
            item["risk_level"] = "medium"

        # ── Step 5: type 归一化 ───────────────────────────────
        # type 已通过 _validate_schema 的枚举校验，此处确保是小写形式
        item["type"] = str(item["type"]).lower()

        try:
            violations.append(LLMViolation(**item))
        except Exception as exc:
            logger.warning(
                "_parse_violations: item[%d] 构造 LLMViolation 失败: %s，丢弃",
                i,
                exc,
            )

    return violations


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
        url = f"{self.api_base.rstrip('/')}/chat/completions"
        # GitHub Models / Azure AI 需要 api-version
        if "models.inference.ai.azure.com" in url:
            url += "?api-version=2024-06-01"
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
            "total_tokens": (data.get("prompt_eval_count", 0) + data.get("eval_count", 0)),
        }
        return content, usage


# ═══════════════════════════════════════════════════════════════
# 引擎主类
# ═══════════════════════════════════════════════════════════════

PROVIDER_COST_ESTIMATES: dict[str, tuple[float, float]] = {
    # (input_cost_per_1k, output_cost_per_1k) 单位：元
    "qwen-turbo": (0.0008, 0.002),
    "qwen-plus": (0.002, 0.006),
    "qwen-max": (0.004, 0.012),
    "deepseek-chat": (0.001, 0.002),
    "deepseek-reasoner": (0.004, 0.016),
    "glm-4-plus": (0.005, 0.005),
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

        # 多模型路由
        self.multi_model_enabled = settings.llm_multi_model_enabled
        self._model_router: Optional[ModelRouter] = None
        if self.multi_model_enabled:
            self._model_router = ModelRouter(settings.llm_multi_model_config)
            logger.info(
                "多模型路由已启用，配置文件: %s", settings.llm_multi_model_config
            )

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
                    tmpl.name,
                    tmpl.version,
                    tmpl.path,
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

    def _build_provider_for_config(self, config: dict) -> BaseProvider:
        """根据模型路由配置创建 Provider 实例"""
        provider_name = config.get("provider", "openai_compatible")
        api_base = config.get("api_base", self.api_base)
        model = config.get("model", self.model)
        api_key = config.get("api_key", "") or ""
        # 尝试通过 api_key_env 解析密钥
        if not api_key and self._model_router:
            api_key = self._model_router.get_api_key(config)
        if not api_key:
            api_key = self.api_key  # fallback to default

        provider_map: dict[str, type[BaseProvider]] = {
            "openai_compatible": OpenAICompatibleProvider,
            "ollama": OllamaProvider,
        }
        cls = provider_map.get(provider_name)
        if not cls:
            logger.warning(
                "未知 Provider '%s'，回退到 openai_compatible",
                provider_name,
            )
            cls = OpenAICompatibleProvider
        return cls(api_base, api_key, model)

    def _get_models_for_chunk(self, chunk: dict) -> list[tuple[str, dict]]:
        """返回处理某个 chunk 需要用到的一组 (model_name, model_config)。

        多模型模式：返回所有配置的模型（去重）
        单模型模式：返回唯一默认模型
        """
        if not self.multi_model_enabled or not self._model_router:
            # 单模型：返回当前默认 provider 的配置
            return [(self.model, {
                "provider": self.provider_name,
                "api_base": self.api_base,
                "model": self.model,
                "api_key_env": "",
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "cost_per_1k_input": self.cost_per_1k_input,
                "cost_per_1k_output": self.cost_per_1k_output,
            })]

        # 多模型：收集所有不重复的模型
        seen_models: set[str] = set()
        result: list[tuple[str, dict]] = []

        # 先添加默认模型
        default_config = self._model_router.model_configs.get(
            self._model_router.default_model
        )
        if default_config:
            seen_models.add(self._model_router.default_model)
            result.append((self._model_router.default_model, default_config))

        # 再添加路由表中引用的其他模型
        for model_name in self._model_router.dimension_routing.values():
            if model_name not in seen_models:
                config = self._model_router.model_configs.get(model_name)
                if config:
                    seen_models.add(model_name)
                    result.append((model_name, config))

        if not result:
            # 兜底：使用默认 provider
            return [(self.model, {
                "provider": self.provider_name,
                "api_base": self.api_base,
                "model": self.model,
                "api_key_env": "",
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "cost_per_1k_input": self.cost_per_1k_input,
                "cost_per_1k_output": self.cost_per_1k_output,
            })]

        logger.debug("多模型路由: %d 个模型将被调用", len(result))
        return result

    async def _call_model_with_retry(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        model_config: dict,
        model_name: str,
    ) -> tuple[list[LLMViolation], dict, Optional[str]]:
        """调用指定模型的 Provider 并解析结果

        Args:
            client: httpx 客户端
            prompt: Prompt 内容
            model_config: 模型配置 dict（含 provider/api_base/model 等）
            model_name: 模型名称（用于日志和成本计算）

        Returns:
            (violations, usage_dict, error_message)
        """
        provider = self._build_provider_for_config(model_config)
        max_tokens = model_config.get("max_tokens", self.max_tokens)
        temperature = model_config.get("temperature", self.temperature)

        last_error: Optional[str] = None
        for attempt in range(1, self.retry_count + 2):
            try:
                content, usage = await provider.chat(
                    prompt,
                    client,
                    max_tokens,
                    temperature,
                )
                raw = _extract_json(content)
                if raw is None:
                    raise ValueError(f"LLM 返回非 JSON 格式: {content[:200]}...")
                violations = _parse_violations(raw)
                return violations, usage, None

            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}"
                logger.warning(
                    "模型 [%s] 调用失败 (attempt %d/%d): %s",
                    model_name,
                    attempt,
                    self.retry_count + 1,
                    last_error,
                )
            except httpx.TimeoutException:
                last_error = "超时"
                logger.warning(
                    "模型 [%s] 超时 (attempt %d/%d)",
                    model_name,
                    attempt,
                    self.retry_count + 1,
                )
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                last_error = str(e)
                logger.warning(
                    "模型 [%s] 响应解析失败 (attempt %d/%d): %s",
                    model_name,
                    attempt,
                    self.retry_count + 1,
                    last_error,
                )
                return [], {}, last_error
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.error(
                    "模型 [%s] 未知错误 (attempt %d/%d): %s",
                    model_name,
                    attempt,
                    self.retry_count + 1,
                    last_error,
                )

            if attempt <= self.retry_count:
                delay = self.retry_delay * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

        return [], {}, last_error

    def _deduplicate_violations(
        self,
        violations: list[LLMViolation],
    ) -> list[LLMViolation]:
        """合并去重：按 (type, section, text 前缀) 去重，保留置信度最高的"""
        if not violations:
            return []

        keyed: dict[str, LLMViolation] = {}
        for v in violations:
            # 生成去重键：类型 + 章节 + 文本前 40 字符
            key = f"{v.type}|{v.section}|{v.text[:40]}"
            if key in keyed:
                # 保留置信度更高的
                if v.confidence > keyed[key].confidence:
                    keyed[key] = v
            else:
                keyed[key] = v

        return list(keyed.values())

    def _calc_cost_for_model(
        self, input_tokens: int, output_tokens: int, model_config: dict
    ) -> float:
        """根据模型配置计算成本"""
        in_cost = model_config.get("cost_per_1k_input", 0)
        out_cost = model_config.get("cost_per_1k_output", 0)
        if in_cost > 0 or out_cost > 0:
            return input_tokens / 1000 * in_cost + output_tokens / 1000 * out_cost

        # 回退到全局估算
        model_name = model_config.get("model", "")
        for prefix, (ic, oc) in PROVIDER_COST_ESTIMATES.items():
            if model_name.startswith(prefix):
                return input_tokens / 1000 * ic + output_tokens / 1000 * oc

        return self._calc_cost(input_tokens, output_tokens)

    async def _process_chunk(
        self,
        client: httpx.AsyncClient,
        chunk: dict,
        models: list[tuple[str, dict]],
    ) -> tuple[list[LLMViolation], dict, Optional[str], float]:
        """Process a single chunk by calling the appropriate LLM(s).

        Supports both single-model and multi-model (parallel) calling.
        Each chunk is independent — safe to call concurrently for multiple chunks.

        Returns:
            (violations, usage_dict, error_message, duration_seconds)
        """
        t_start = time.monotonic()

        if self.multi_model_enabled and len(models) > 1:
            # ── Multi-model mode: parallel calls for this chunk ──
            tasks = []
            for model_name, model_cfg in models:
                tasks.append(
                    self._call_model_with_retry(
                        client, chunk["prompt"], model_cfg, model_name,
                    )
                )
            results = await asyncio.gather(*tasks, return_exceptions=True)
            chunk_violations: list[LLMViolation] = []
            chunk_usage_total: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
            chunk_err: Optional[str] = None

            for i, result in enumerate(results):
                model_name = models[i][0]
                if isinstance(result, Exception):
                    chunk_err = f"{model_name}: {result}"
                    logger.warning("Model [%s] call exception: %s", model_name, result)
                    continue
                violations, usage, err = result
                if err:
                    if not chunk_err:
                        chunk_err = err
                    logger.warning("Model [%s] returned error: %s", model_name, err)
                chunk_usage_total["prompt_tokens"] += usage.get("prompt_tokens", 0)
                chunk_usage_total["completion_tokens"] += usage.get("completion_tokens", 0)
                if violations:
                    chunk_violations.extend(violations)
        else:
            # ── Single-model mode ──
            model_name, model_cfg = models[0]
            chunk_violations, chunk_usage_total, chunk_err = (
                await self._call_model_with_retry(
                    client, chunk["prompt"], model_cfg, model_name,
                )
            )

        duration = time.monotonic() - t_start
        return chunk_violations, chunk_usage_total, chunk_err, duration

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
            sections = {k: v for k, v in sections.items() if k in target_section_types}
            if not sections:
                logger.info("目标章节类型 %s 均未在文档中找到，跳过 LLM 分析", target_section_types)
                return LLMEngineResult(
                    model_used=self.model,
                    sections_analyzed=0,
                    sections_skipped=0,
                )
        if rule_violations:
            violated_sections = _extract_violated_sections(
                rule_violations,
                all_section_names,
            )
            n_violated = len(violated_sections)
            n_clean = len(all_section_names) - n_violated
            logger.info(
                "成本优化: %d 个章节有规则违规(100%%必检), %d 个章节无违规(30%%抽样)",
                n_violated,
                n_clean,
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

        # ── 确定要调用的模型列表 ─────────────────────────────
        models = self._get_models_for_chunk(chunks[0])
        model_names = [name for name, _ in models]
        models_used_str = "+".join(model_names) if models else self.model

        all_violations: list[LLMViolation] = []
        total_input_tokens = 0
        total_output_tokens = 0
        sections_ok = 0
        last_error: Optional[str] = None

        timeout_cfg = httpx.Timeout(self.timeout, connect=15.0)
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)

        # ── 并行处理多个 chunk（每个 chunk 独立，安全并发） ──
        async with httpx.AsyncClient(timeout=timeout_cfg, limits=limits) as client:
            tasks = [self._process_chunk(client, chunk, models) for chunk in chunks]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            chunk = chunks[i]

            if isinstance(result, Exception):
                logger.warning(
                    "章节 [%s] 并行处理异常: %s",
                    chunk["section_name"],
                    result,
                )
                last_error = str(result)
                continue

            chunk_violations, chunk_usage_total, chunk_err, duration = result

            pt = chunk_usage_total.get("prompt_tokens", 0)
            ct = chunk_usage_total.get("completion_tokens", 0)
            total_input_tokens += pt
            total_output_tokens += ct

            # ── Record usage ─────────────────────────────
            if not self.mock_mode:
                chunk_cost = self._calc_cost_for_model(
                    pt, ct,
                    {"cost_per_1k_input": self.cost_per_1k_input,
                     "cost_per_1k_output": self.cost_per_1k_output,
                     "model": models_used_str},
                )
                self.usage_tracker.record_call(
                    model=models_used_str,
                    provider=self.provider_name,
                    prompt_tokens=pt,
                    completion_tokens=ct,
                    duration_seconds=duration,
                    cost_yuan=chunk_cost,
                    success=(chunk_err is None),
                    error_message=chunk_err or "",
                    file_id=file_id,
                    user_id=user_id,
                    section_name=chunk["section_name"],
                    prompt_length=len(chunk["prompt"]),
                )

            if chunk_violations:
                for v in chunk_violations:
                    if not v.section:
                        v.section = chunk["section_name"]
                all_violations.extend(chunk_violations)
                sections_ok += 1
            elif chunk_err:
                last_error = chunk_err
                logger.warning(
                    "章节 [%s] 审查失败: %s",
                    chunk["section_name"],
                    chunk_err,
                )
            else:
                sections_ok += 1  # no violations is also success

        total_tokens = total_input_tokens + total_output_tokens

        # ── 去重合并 ─────────────────────────────────────────
        all_violations = self._deduplicate_violations(all_violations)

        # 计算成本
        cost = self._calc_cost(total_input_tokens, total_output_tokens)

        # 综合评分
        total_deduction = sum(v.weight for v in all_violations)
        total_score = max(0.0, 100.0 - total_deduction)

        return LLMEngineResult(
            violations=all_violations,
            total_score=round(total_score, 1),
            model_used=models_used_str,
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
                    prompt,
                    client,
                    self.max_tokens,
                    self.temperature,
                )

                # 解析 JSON
                raw = _extract_json(content)
                if raw is None:
                    raise ValueError(f"LLM 返回非 JSON 格式: {content[:200]}...")

                violations = _parse_violations(raw)
                return violations, usage, None

            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}"
                logger.warning(
                    "LLM 调用失败 (attempt %d/%d): %s",
                    attempt,
                    self.retry_count + 1,
                    last_error,
                )
            except httpx.TimeoutException:
                last_error = "超时"
                logger.warning(
                    "LLM 超时 (attempt %d/%d)",
                    attempt,
                    self.retry_count + 1,
                )
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                last_error = str(e)
                logger.warning(
                    "LLM 响应解析失败 (attempt %d/%d): %s",
                    attempt,
                    self.retry_count + 1,
                    last_error,
                )
                # 解析错误不重试——模型能返回 JSON 但格式不对，重试一般无用
                return [], {}, last_error
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.error(
                    "LLM 未知错误 (attempt %d/%d): %s",
                    attempt,
                    self.retry_count + 1,
                    last_error,
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
                return input_tokens / 1000 * in_cost + output_tokens / 1000 * out_cost

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
            and hasattr(marked_doc, "stats")
            and marked_doc.stats.get("method") == "fingerprint"
        )

        # ── 获取每个章节需要检查的文本 ────────
        def _check_text(sec_name: str, sec_text: str) -> str:
            """返回该章节需要检查的文本"""
            if is_fingerprint_mode and marked_doc and hasattr(marked_doc, "get_variable_text"):
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
                    evidence="原文限定供应商注册地为本市，构成地域歧视",
                    consequence="若不修正，将导致外地供应商无法参与，引发供应商质疑投诉，平台审查时将直接退回，严重情形下可能被财政部门认定为以不合理条件限制供应商，面临行政处罚",
                    confidence=0.92,
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
                    evidence="原文明确指定了特定品牌，排除了其他合格品牌参与竞争",
                    consequence="若不修正，平台形式审查将直接拦截，供应商可依据《政府采购法》第二十二条提出质疑投诉，行政机关可责令改正并处以罚款",
                    confidence=0.95,
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
                    evidence="评分标准条款中存在倾斜性指标设置",
                    consequence="若不修正，落选供应商可能据此提出质疑投诉，影响采购效率，严重时可能导致中标结果无效",
                    confidence=0.78,
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
                    evidence="原文将注册资金金额作为投标资格条件",
                    consequence="若不修正，以注册资金门槛排斥中小企业参与，违反政府采购促进中小企业发展政策，供应商可依据《政府采购法实施条例》第二十条提出质疑",
                    confidence=0.85,
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
                    evidence="原文使用排他性限定词，限制了合格供应商的范围",
                    consequence="若不修正，被排斥的供应商可依据《政府采购法》提出质疑投诉，平台审查时将退回修改",
                    confidence=0.90,
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
                    evidence="原文使用了模糊措辞，缺乏明确可量化的判断标准",
                    consequence="若不修正，供应商可能对评审结果提出质疑，认为评审标准不明确导致评审不公，增加投诉风险",
                    confidence=0.72,
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
                            v.text = sec_text[max(0, idx - 15) : idx + 30].strip()
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
