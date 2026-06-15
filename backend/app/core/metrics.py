"""Prometheus 指标收集与暴露

核心指标：
- HTTP 请求计数与耗时（按 method/endpoint/status）
- LLM 调用计数、Token 消耗、耗时（按 model）
- 合规检查违规计数器（按 severity/rule_type）
- 文件上传统计（按扩展名/大小）
- DB 连接池状态

通过 GET /metrics 暴露为 Prometheus 文本格式。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Optional

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    REGISTRY,
)

# ── 独立 registry 避免与其它库冲突 ────────────────────────
_metrics_registry: CollectorRegistry = REGISTRY


# ═══════════════════════════════════════════════════════════════
# HTTP 指标
# ═══════════════════════════════════════════════════════════════

http_requests_total = Counter(
    "bhg_http_requests_total",
    "HTTP 请求总数",
    ["method", "endpoint", "status_code"],
    registry=_metrics_registry,
)

http_request_duration_seconds = Histogram(
    "bhg_http_request_duration_seconds",
    "HTTP 请求耗时（秒）",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0],
    registry=_metrics_registry,
)

# ═══════════════════════════════════════════════════════════════
# 业务指标
# ═══════════════════════════════════════════════════════════════

llm_calls_total = Counter(
    "bhg_llm_calls_total",
    "LLM 调用总数",
    ["model", "success"],
    registry=_metrics_registry,
)

llm_tokens_total = Counter(
    "bhg_llm_tokens_total",
    "LLM Token 消耗总数",
    ["model", "type"],  # type = input / output
    registry=_metrics_registry,
)

llm_cost_yuan_total = Counter(
    "bhg_llm_cost_yuan_total",
    "LLM 人民币成本总数",
    ["model"],
    registry=_metrics_registry,
)

llm_duration_seconds = Histogram(
    "bhg_llm_duration_seconds",
    "LLM 调用耗时（秒）",
    ["model"],
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 40.0, 60.0, 120.0],
    registry=_metrics_registry,
)

check_violations_total = Counter(
    "bhg_check_violations_total",
    "合规检查发现的违规总数",
    ["severity", "rule_type", "source"],
    registry=_metrics_registry,
)

check_duration_seconds = Histogram(
    "bhg_check_duration_seconds",
    "合规检查总耗时（秒）",
    ["traffic_light"],
    buckets=[5.0, 10.0, 30.0, 60.0, 120.0, 180.0, 300.0],
    registry=_metrics_registry,
)

file_uploads_total = Counter(
    "bhg_file_uploads_total",
    "文件上传总数",
    ["extension", "status"],
    registry=_metrics_registry,
)

upload_file_size_bytes = Histogram(
    "bhg_upload_file_size_bytes",
    "上传文件大小（字节）",
    ["extension"],
    buckets=[1024, 10240, 102400, 1048576, 5242880, 10485760, 26214400, 52428800],
    registry=_metrics_registry,
)

rules_loaded_gauge = Gauge(
    "bhg_rules_loaded",
    "规则引擎当前加载的规则数",
    registry=_metrics_registry,
)

check_in_progress_gauge = Gauge(
    "bhg_checks_in_progress",
    "当前正在进行中的合规检查数",
    registry=_metrics_registry,
)


# ═══════════════════════════════════════════════════════════════
# 便捷记录函数
# ═══════════════════════════════════════════════════════════════

def record_http(method: str, endpoint: str, status_code: int, duration: float) -> None:
    http_requests_total.labels(method=method, endpoint=endpoint, status_code=str(status_code)).inc()
    http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)


def record_llm_call(
    model: str,
    success: bool,
    tokens_input: int,
    tokens_output: int,
    cost_yuan: float,
    duration: float,
) -> None:
    llm_calls_total.labels(model=model, success=str(success).lower()).inc()
    llm_tokens_total.labels(model=model, type="input").inc(tokens_input)
    llm_tokens_total.labels(model=model, type="output").inc(tokens_output)
    llm_cost_yuan_total.labels(model=model).inc(cost_yuan)
    llm_duration_seconds.labels(model=model).observe(duration)


def record_check_completed(
    traffic_light: str,
    duration: float,
    violations: list[dict],
) -> None:
    """记录一次完整的合规检查结果"""
    check_duration_seconds.labels(traffic_light=traffic_light).observe(duration)
    for v in violations:
        check_violations_total.labels(
            severity=v.get("risk_level", "low"),
            rule_type=v.get("rule_type", "unknown"),
            source=v.get("source", "unknown"),
        ).inc()


def record_file_upload(extension: str, size_bytes: int, success: bool) -> None:
    file_uploads_total.labels(extension=extension, status="success" if success else "error").inc()
    if success:
        upload_file_size_bytes.labels(extension=extension).observe(size_bytes)


@contextmanager
def track_check_in_progress():
    """上下文管理器：包裹合规检查以追踪并发数"""
    check_in_progress_gauge.inc()
    try:
        yield
    finally:
        check_in_progress_gauge.dec()


def track_http_duration(method: str, endpoint: str, status_code: int, duration: float) -> None:
    """便捷函数：记录 HTTP 请求指标"""
    record_http(method, endpoint, status_code, duration)


# ═══════════════════════════════════════════════════════════════
# /metrics 端点数据生成
# ═══════════════════════════════════════════════════════════════

def get_metrics_response() -> str:
    """生成 Prometheus 文本格式的指标数据"""
    return generate_latest(_metrics_registry).decode("utf-8")
