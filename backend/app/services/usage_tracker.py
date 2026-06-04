"""LLM 调用追踪器

记录每次 LLM API 调用的：
  - Token 用量（输入/输出/合计）
  - 模型名称
  - 调用耗时
  - 估算费用
  - 关联的文件 / 请求信息

所有记录保存在内存中，可通过 get_stats() / get_recent() 查询。
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class UsageRecord:
    """单次 LLM 调用的完整记录"""

    # 标识
    request_id: str = ""                   # 请求 ID（由调用方生成）
    file_id: Optional[int] = None          # 关联的文件 ID
    user_id: Optional[int] = None          # 关联的用户 ID

    # 模型信息
    model: str = ""
    provider: str = ""                     # openai_compatible / ollama / mock

    # Token 用量
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # 耗时
    started_at: Optional[float] = None     # time.monotonic()
    duration_seconds: float = 0.0

    # 费用（元）
    cost_yuan: float = 0.0

    # 状态
    success: bool = True
    error_message: str = ""
    retry_count: int = 0                   # 重试次数

    # 请求上下文
    section_name: str = ""                 # 审查的章节名
    section_count: int = 0                 # 本次请求包含的章节数
    prompt_length: int = 0                 # Prompt 字符数

    # 时间戳
    timestamp: str = field(default_factory=lambda: datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S"))

    def dict(self) -> dict:
        """转为 JSON 友好的字典"""
        return {
            "request_id": self.request_id,
            "file_id": self.file_id,
            "user_id": self.user_id,
            "model": self.model,
            "provider": self.provider,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "duration_seconds": round(self.duration_seconds, 3),
            "cost_yuan": round(self.cost_yuan, 6),
            "success": self.success,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "section_name": self.section_name,
            "section_count": self.section_count,
            "timestamp": self.timestamp,
        }


@dataclass
class UsageStats:
    """聚合统计"""
    total_calls: int = 0
    total_tokens: int = 0
    total_cost_yuan: float = 0.0
    total_duration_seconds: float = 0.0
    calls_by_model: dict[str, int] = field(default_factory=dict)
    tokens_by_model: dict[str, int] = field(default_factory=dict)
    cost_by_model: dict[str, float] = field(default_factory=dict)
    success_rate: float = 100.0
    avg_tokens_per_call: float = 0.0
    avg_duration_seconds: float = 0.0


# ═══════════════════════════════════════════════════════════════
# 内置模型定价表
# ═══════════════════════════════════════════════════════════════

MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_cost_per_1k_tokens, output_cost_per_1k_tokens) 单位：元
    # 通义千问
    "qwen-turbo":         (0.0008, 0.002),
    "qwen-plus":          (0.002,  0.006),
    "qwen-max":           (0.004,  0.012),
    "qwen2.5":            (0.0,    0.0),    # Ollama 本地免费
    # DeepSeek
    "deepseek-chat":      (0.001,  0.002),
    "deepseek-reasoner":  (0.004,  0.016),
    # 智谱
    "glm-4-plus":         (0.005,  0.005),
    "glm-4-air":          (0.001,  0.001),
    # 百度
    "ernie-4.0":          (0.012,  0.012),
    "ernie-speed":        (0.0,    0.0),    # 免费
    # 零一万物
    "yi-lightning":       (0.0,    0.0),    # 免费
    # Mock
    "mock":               (0.0,    0.0),
}


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    custom_input_price: float = 0.0,
    custom_output_price: float = 0.0,
) -> float:
    """
    估算调用费用。

    Args:
        model: 模型名称
        prompt_tokens: 输入 token 数
        completion_tokens: 输出 token 数
        custom_input_price: 用户自定义输入单价（元/1K tokens）
        custom_output_price: 用户自定义输出单价

    Returns:
        费用（元）
    """
    if custom_input_price > 0 or custom_output_price > 0:
        in_price = custom_input_price
        out_price = custom_output_price
    else:
        # 按模型前缀匹配
        in_price = out_price = 0.0
        for prefix, (p_in, p_out) in MODEL_PRICING.items():
            if model.startswith(prefix):
                in_price, out_price = p_in, p_out
                break

    return (
        prompt_tokens / 1000 * in_price
        + completion_tokens / 1000 * out_price
    )


# ═══════════════════════════════════════════════════════════════
# 追踪器
# ═══════════════════════════════════════════════════════════════

class LLMUsageTracker:
    """
    LLM 调用追踪器。

    记录每次 API 调用的 Token、耗时、费用，并提供聚合统计。

    示例::
        tracker = LLMUsageTracker()

        # 记录一次调用
        tracker.record(UsageRecord(
            model="qwen2.5:14b",
            prompt_tokens=500,
            completion_tokens=200,
            duration_seconds=3.2,
            file_id=42,
        ))

        # 统计
        stats = tracker.get_stats()
        print(f"总调用: {stats.total_calls}, 总费用: ¥{stats.total_cost_yuan}")

        # 最近记录
        for rec in tracker.get_recent(5):
            print(rec.dict())
    """

    def __init__(self, max_records: int = 10000):
        self._records: deque[UsageRecord] = deque(maxlen=max_records)

    # ── 记录 ────────────────────────────────────────────────

    def record(self, record: UsageRecord) -> None:
        """添加一条调用记录。"""
        self._records.append(record)

    def record_call(
        self,
        *,
        model: str,
        provider: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_seconds: float = 0.0,
        cost_yuan: float = 0.0,
        success: bool = True,
        error_message: str = "",
        retry_count: int = 0,
        file_id: Optional[int] = None,
        user_id: Optional[int] = None,
        section_name: str = "",
        section_count: int = 0,
        prompt_length: int = 0,
        request_id: str = "",
    ) -> UsageRecord:
        """
        便捷方法：用关键字参数创建记录并保存。

        Returns:
            创建的 UsageRecord
        """
        if not cost_yuan:
            cost_yuan = estimate_cost(model, prompt_tokens, completion_tokens)

        record = UsageRecord(
            request_id=request_id,
            file_id=file_id,
            user_id=user_id,
            model=model,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            duration_seconds=duration_seconds,
            cost_yuan=cost_yuan,
            success=success,
            error_message=error_message,
            retry_count=retry_count,
            section_name=section_name,
            section_count=section_count,
            prompt_length=prompt_length,
        )
        self.record(record)
        return record

    # ── 查询 ────────────────────────────────────────────────

    def get_stats(self) -> UsageStats:
        """
        聚合所有记录的统计信息。
        """
        total = len(self._records)
        if total == 0:
            return UsageStats()

        total_tokens = 0
        total_cost = 0.0
        total_duration = 0.0
        success_count = 0
        calls_by_model: dict[str, int] = {}
        tokens_by_model: dict[str, int] = {}
        cost_by_model: dict[str, float] = {}

        for rec in self._records:
            total_tokens += rec.total_tokens
            total_cost += rec.cost_yuan
            total_duration += rec.duration_seconds
            if rec.success:
                success_count += 1

            calls_by_model[rec.model] = calls_by_model.get(rec.model, 0) + 1
            tokens_by_model[rec.model] = (
                tokens_by_model.get(rec.model, 0) + rec.total_tokens
            )
            cost_by_model[rec.model] = (
                cost_by_model.get(rec.model, 0) + rec.cost_yuan
            )

        return UsageStats(
            total_calls=total,
            total_tokens=total_tokens,
            total_cost_yuan=round(total_cost, 4),
            total_duration_seconds=round(total_duration, 3),
            calls_by_model=calls_by_model,
            tokens_by_model=tokens_by_model,
            cost_by_model={k: round(v, 4) for k, v in cost_by_model.items()},
            success_rate=round(success_count / total * 100, 1),
            avg_tokens_per_call=round(total_tokens / total, 1),
            avg_duration_seconds=round(total_duration / total, 3),
        )

    def get_recent(self, n: int = 10) -> list[UsageRecord]:
        """
        返回最近 N 条记录（新区在前）。
        """
        return list(self._records)[-n:][::-1]

    def get_by_file(self, file_id: int) -> list[UsageRecord]:
        """返回指定文件的所有记录。"""
        return [r for r in self._records if r.file_id == file_id]

    def get_by_user(self, user_id: int) -> list[UsageRecord]:
        """返回指定用户的所有记录。"""
        return [r for r in self._records if r.user_id == user_id]

    def get_failures(self, n: int = 20) -> list[UsageRecord]:
        """返回最近失败的调用记录。"""
        return [r for r in self._records if not r.success][-n:][::-1]

    # ── 维护 ────────────────────────────────────────────────

    def clear(self) -> None:
        """清空所有记录。"""
        self._records.clear()

    def __len__(self) -> int:
        return len(self._records)

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"<LLMUsageTracker total_calls={stats.total_calls} "
            f"total_tokens={stats.total_tokens} "
            f"total_cost=¥{stats.total_cost_yuan}>"
        )


# 模块级单例（全局共享，所有请求共用）
usage_tracker = LLMUsageTracker()
