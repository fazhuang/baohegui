"""ExecutionNode — the atomic unit of work in a DAG-based compliance check."""
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from app.runtime.node_types import NodeType


@dataclass
class RetryPolicy:
    """Retry configuration for an ExecutionNode."""
    max_retries: int = 0
    backoff_seconds: float = 0.0
    backoff_multiplier: float = 1.0


@dataclass
class ExecutionNode:
    """A single node in the compliance check DAG.

    Each node wraps an existing engine function with input/output schemas,
    audit requirements, and retry policy.
    """

    node_id: str
    node_type: NodeType
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    dependencies: list[str]
    timeout: float
    retry_policy: RetryPolicy
    deterministic: bool
    audit_required: bool
    replay_required: bool
    execute: Callable[..., Any]
