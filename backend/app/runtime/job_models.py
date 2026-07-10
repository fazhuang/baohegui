"""Job models — status enum and data class for the job orchestrator."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    NODE_FAILED = "NODE_FAILED"
    FAILED = "FAILED"
    SUCCEEDED = "SUCCEEDED"
    CANCELLED = "CANCELLED"
    REPLAYING = "REPLAYING"

    @classmethod
    def terminal(cls) -> set[JobStatus]:
        return {cls.SUCCEEDED, cls.FAILED, cls.CANCELLED}

    @classmethod
    def valid_transitions(cls) -> dict[JobStatus, set[JobStatus]]:
        return {
            cls.PENDING: {cls.RUNNING, cls.CANCELLED},
            cls.RUNNING: {cls.SUCCEEDED, cls.NODE_FAILED, cls.FAILED, cls.CANCELLED},
            cls.NODE_FAILED: {cls.RUNNING, cls.FAILED, cls.CANCELLED},
            cls.FAILED: set(),
            cls.SUCCEEDED: {cls.REPLAYING},
            cls.CANCELLED: set(),
            cls.REPLAYING: {cls.SUCCEEDED, cls.FAILED, cls.CANCELLED},
        }


@dataclass
class Job:
    """A single compliance check job."""

    job_id: str
    tenant_id: str
    file_id: str
    status: JobStatus
    graph_json: str  # JSON serialized ExecutionGraph
    current_node: str | None = None
    error_json: dict[str, Any] | None = None
    result_json: dict[str, Any] | None = None
    trace_json: dict[str, Any] | None = None
    replay_from: str | None = None
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None
