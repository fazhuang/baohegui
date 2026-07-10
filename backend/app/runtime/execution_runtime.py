"""ExecutionRuntime — executes an ExecutionGraph with topological ordering and lightweight parallelism."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable, Awaitable
from dataclasses import dataclass, field
from typing import Any

from app.runtime.execution_node import ExecutionNode
from app.runtime.execution_graph import ExecutionGraph
from app.runtime.node_types import NodeType


@dataclass
class NodeFailure:
    """Record of a node execution failure."""

    node_id: str
    node_type: NodeType
    error: str
    traceback: str
    retries_exhausted: bool = False


@dataclass
class TraceStep:
    """A single step in the dynamic audit trace."""

    sequence: int
    node_id: str
    node_type: NodeType
    input_hash: str
    output_hash: str
    previous_hash: str
    deterministic: bool
    duration_ms: int
    error: str | None = None


class AuditTrace:
    """Dynamic audit trace — steps are appended as nodes execute."""

    def __init__(self, root_hash: str = "") -> None:
        self.steps: list[TraceStep] = []
        self.root_hash: str = root_hash
        self.leaf_hash: str = root_hash

    def append_step(
        self,
        node_id: str,
        node_type: NodeType,
        input_hash: str,
        output_hash: str,
        deterministic: bool,
        duration_ms: int,
        error: str | None = None,
    ) -> None:
        step = TraceStep(
            sequence=len(self.steps),
            node_id=node_id,
            node_type=node_type,
            input_hash=input_hash,
            output_hash=output_hash,
            previous_hash=self.leaf_hash,
            deterministic=deterministic,
            duration_ms=duration_ms,
            error=error,
        )
        self.steps.append(step)
        self.leaf_hash = output_hash


def _stable_hash(obj: Any) -> str:
    """Deterministic SHA-256 hash of a JSON-serializable object."""
    raw = json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


_CRITICAL_NODE_TYPES: set[NodeType] = {NodeType.POLICY_KERNEL}


class ExecutionRuntime:
    """Executes an ExecutionGraph node by node, respecting dependencies.

    Nodes with no data dependencies on each other may run in parallel.
    Currently the only such pair is RULE_CHECK || LLM_CHECK.
    """

    def __init__(self) -> None:
        self._trace: AuditTrace | None = None

    async def execute(
        self,
        graph: ExecutionGraph,
        *,
        on_step: Callable[[str, str], Awaitable[None]] | None = None,
        fail_fast_on_high_risk: bool = False,
    ) -> dict[str, Any]:
        """Execute the graph. Returns {node_id: output | NodeFailure}.

        Raises ValueError on POLICY_KERNEL failure when fail_fast_on_high_risk=True.
        """
        graph.validate()
        order = graph.topological_order()
        results: dict[str, Any] = {}
        self._trace = AuditTrace(root_hash=_stable_hash({"job_id": graph.job_id}))

        # Build remaining deps tracking for ready-set management
        remaining_deps: dict[str, set[str]] = {}
        for nid in order:
            node = graph.get_node(nid)
            remaining_deps[nid] = set(node.dependencies)

        ready: set[str] = {nid for nid in order if not remaining_deps[nid]}
        completed: set[str] = set()

        async def run_node(nid: str) -> None:
            node = graph.get_node(nid)
            if on_step:
                await on_step(nid, "running")

            input_data: dict[str, Any] = {}
            for dep in node.dependencies:
                dep_result = results.get(dep)
                if isinstance(dep_result, NodeFailure):
                    # ponytail: upstream failure — skip downstream
                    results[nid] = NodeFailure(
                        node_id=nid,
                        node_type=node.node_type,
                        error=f"Upstream dependency '{dep}' failed: {dep_result.error}",
                        traceback="",
                    )
                    self._trace.append_step(
                        node_id=nid,
                        node_type=node.node_type,
                        input_hash=_stable_hash({}),
                        output_hash=_stable_hash({"skipped": True, "reason": dep_result.error}),
                        deterministic=node.deterministic,
                        duration_ms=0,
                        error=f"Upstream dependency '{dep}' failed",
                    )
                    if on_step:
                        await on_step(nid, "skipped")
                    completed.add(nid)
                    return
                input_data[dep] = dep_result

            input_hash = _stable_hash(input_data)
            start = time.monotonic()

            last_error: Exception | None = None
            attempts = 1 + node.retry_policy.max_retries

            for attempt in range(attempts):
                last_error = None
                try:
                    coro = node.execute(input_data)
                    if asyncio.iscoroutine(coro):
                        output = await asyncio.wait_for(coro, timeout=node.timeout)
                    else:
                        output = coro
                    break
                except asyncio.TimeoutError:
                    last_error = TimeoutError(
                        f"Node '{nid}' timeout after {node.timeout}s"
                    )
                    if attempt < attempts - 1:
                        backoff = node.retry_policy.backoff_seconds * (
                            node.retry_policy.backoff_multiplier ** attempt
                        )
                        await asyncio.sleep(backoff)
                except Exception as e:
                    last_error = e
                    if attempt < attempts - 1:
                        backoff = node.retry_policy.backoff_seconds * (
                            node.retry_policy.backoff_multiplier ** attempt
                        )
                        await asyncio.sleep(backoff)

            duration_ms = int((time.monotonic() - start) * 1000)

            if last_error is not None:
                output_hash = _stable_hash({"error": str(last_error)})
                results[nid] = NodeFailure(
                    node_id=nid,
                    node_type=node.node_type,
                    error=str(last_error),
                    traceback=str(getattr(last_error, "__traceback__", "")),
                    retries_exhausted=(attempts > 1),
                )
                self._trace.append_step(
                    node_id=nid,
                    node_type=node.node_type,
                    input_hash=input_hash,
                    output_hash=output_hash,
                    deterministic=node.deterministic,
                    duration_ms=duration_ms,
                    error=str(last_error),
                )
                if fail_fast_on_high_risk and node.node_type in _CRITICAL_NODE_TYPES:
                    raise ValueError(str(last_error)) from last_error
            else:
                output_hash = _stable_hash(output)
                results[nid] = output
                self._trace.append_step(
                    node_id=nid,
                    node_type=node.node_type,
                    input_hash=input_hash,
                    output_hash=output_hash,
                    deterministic=node.deterministic,
                    duration_ms=duration_ms,
                    error=None,
                )

            if on_step:
                await on_step(nid, "completed")
            completed.add(nid)

        # Execute: process ready nodes, potentially in parallel within the same rank
        while ready:
            ready_list = sorted(ready)

            # Check if RULE_CHECK and LLM_CHECK are both ready — run them in parallel
            parallel_group: list[str] = []
            for nid in ready_list:
                node = graph.get_node(nid)
                if node.node_type in (NodeType.RULE_CHECK, NodeType.LLM_CHECK):
                    parallel_group.append(nid)

            if len(parallel_group) == 2:
                await asyncio.gather(
                    run_node(parallel_group[0]),
                    run_node(parallel_group[1]),
                )
                ready -= set(parallel_group)
            else:
                nid = ready_list[0]
                ready.discard(nid)
                await run_node(nid)

            # Check for newly ready nodes
            # Find nodes whose dependencies are all completed
            new_ready: set[str] = set()
            for nid in order:
                if nid in completed or nid in ready:
                    continue
                if remaining_deps[nid].issubset(completed):
                    new_ready.add(nid)
            ready |= new_ready

        return results

    @property
    def trace(self) -> AuditTrace | None:
        return self._trace
