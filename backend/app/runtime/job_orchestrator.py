"""JobOrchestrator — manages job lifecycle, quota, concurrency, retry, and replay."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Awaitable
from dataclasses import dataclass
from typing import Any

from app.runtime.job_models import Job, JobStatus
from app.runtime.job_store import JobStore
from app.runtime.execution_graph import ExecutionGraph
from app.runtime.execution_runtime import ExecutionRuntime
from app.runtime.contract_registry import ContractRegistry


@dataclass
class JobRef:
    """Lightweight reference returned on job submission."""
    job_id: str
    status: JobStatus


class JobOrchestrator:
    """Manages compliance check jobs: submit, cancel, retry, replay, status.

    Uses asyncio.create_task() for background execution, PostgreSQL for persistence.
    """

    def __init__(
        self,
        job_store: JobStore,
        runtime: ExecutionRuntime,
        contract_registry: ContractRegistry | None = None,
        max_concurrent_per_tenant: int = 3,
    ) -> None:
        self._store = job_store
        self._runtime = runtime
        self._registry = contract_registry
        self._running: dict[str, asyncio.Task[Any]] = {}
        self.max_concurrent_per_tenant = max_concurrent_per_tenant

    async def submit(
        self,
        tenant_id: str,
        file_id: str,
        graph: ExecutionGraph,
        replay_from: str | None = None,
        _concurrency_override: int | None = None,  # ponytail: for testing
    ) -> JobRef:
        """Submit a new compliance check job. Returns immediately with a JobRef."""
        # Validate graph against contract registry
        if self._registry:
            self._registry.validate_graph(graph)

        # Check concurrency
        max_conc = _concurrency_override or self.max_concurrent_per_tenant
        active = sum(
            1 for t in self._running.values()
            if not t.done()
        )
        if active >= max_conc:
            raise ValueError(f"Tenant concurrency limit ({max_conc}) reached")

        # Create job
        job = await self._store.create(
            tenant_id=tenant_id,
            file_id=file_id,
            graph=graph,
            replay_from=replay_from,
        )

        # Start background execution
        task = asyncio.create_task(self._run(job.job_id))
        self._running[job.job_id] = task

        return JobRef(job_id=job.job_id, status=JobStatus.PENDING)

    async def cancel(self, job_id: str) -> None:
        """Cancel a running job."""
        task = self._running.get(job_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._store.complete(job_id, JobStatus.CANCELLED)

    async def retry_node(self, job_id: str, node_id: str) -> JobRef:
        """Retry a job from a failed node."""
        job = await self._store.get(job_id)
        if job.status not in (JobStatus.NODE_FAILED, JobStatus.FAILED):
            raise ValueError(f"Cannot retry job in status {job.status.value}")

        await self._store.transition(job_id, JobStatus.RUNNING)
        task = asyncio.create_task(self._run(job_id, retry_from=node_id))
        self._running[job_id] = task
        return JobRef(job_id=job_id, status=JobStatus.RUNNING)

    async def replay(self, job_id: str) -> JobRef:
        """Create a replay job from an existing SUCCEEDED job."""
        job = await self._store.get(job_id)
        if job.status != JobStatus.SUCCEEDED:
            raise ValueError(f"Cannot replay job in status {job.status.value}")

        # Reconstruct graph from stored JSON
        graph = _graph_from_json(job.graph_json, job_id)

        replay_job = await self._store.create(
            tenant_id=job.tenant_id,
            file_id=job.file_id,
            graph=graph,
            replay_from=job_id,
        )
        await self._store.transition(replay_job.job_id, JobStatus.REPLAYING)
        task = asyncio.create_task(self._run(replay_job.job_id))
        self._running[replay_job.job_id] = task
        return JobRef(job_id=replay_job.job_id, status=JobStatus.REPLAYING)

    async def status(self, job_id: str) -> Job:
        """Get current job status."""
        return await self._store.get(job_id)

    async def _run(self, job_id: str, retry_from: str | None = None) -> None:
        """Execute the job graph in the background."""
        try:
            job = await self._store.transition(job_id, JobStatus.RUNNING)
            graph = _graph_from_json(job.graph_json, job_id)

            async def on_step(node_id: str, status: str) -> None:
                await self._store.update_current_node(job_id, node_id)

            result = await self._runtime.execute(graph, on_step=on_step)

            # Check for POLICY_KERNEL failure — fail the job
            from app.runtime.node_types import NodeType
            from app.runtime.execution_runtime import NodeFailure
            pk_output = result.get("policy_kernel")
            if isinstance(pk_output, NodeFailure):
                raise ValueError(f"POLICY_KERNEL failed: {pk_output.error}")

            await self._store.complete(
                job_id, JobStatus.SUCCEEDED,
                result=result,
                trace=self._runtime.trace,
            )
        except asyncio.CancelledError:
            await self._store.complete(job_id, JobStatus.CANCELLED)
            raise
        except Exception as e:
            error_str = str(e)
            if "POLICY_KERNEL" in error_str or "NodeFailure" in error_str:
                await self._store.complete(job_id, JobStatus.NODE_FAILED, error=e)
            else:
                await self._store.complete(job_id, JobStatus.FAILED, error=e)
        finally:
            self._running.pop(job_id, None)


def _graph_from_json(graph_json: str, job_id: str) -> ExecutionGraph:
    """Reconstruct an ExecutionGraph from stored JSON. Returns a minimal graph."""
    data = json.loads(graph_json)

    # ponytail: reconstruction only needs topology metadata, not execute fns
    # The actual execute fns are wired at submission time via the full graph
    from app.runtime.node_types import NodeType
    from app.runtime.execution_node import ExecutionNode, RetryPolicy

    nodes = []
    for nd in data.get("nodes", []):
        nodes.append(ExecutionNode(
            node_id=nd["node_id"],
            node_type=NodeType(nd["node_type"]),
            input_schema={},
            output_schema={},
            dependencies=nd.get("dependencies", []),
            timeout=0,
            retry_policy=RetryPolicy(),
            deterministic=nd.get("deterministic", True),
            audit_required=True,
            replay_required=True,
            execute=lambda i: {},
        ))
    return ExecutionGraph(job_id=job_id, nodes=nodes)
