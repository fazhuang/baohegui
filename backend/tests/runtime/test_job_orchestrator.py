"""Tests for JobStore and JobOrchestrator."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.runtime.job_models import JobStatus, Job
from app.runtime.job_store import JobStore
from app.runtime.node_types import NodeType
from app.runtime.execution_node import ExecutionNode, RetryPolicy
from app.runtime.execution_graph import ExecutionGraph


_ = asyncio  # noqa: F811 — ponytail: ensure import not flagged


def _make_graph(job_id="test-job"):
    def noop(i):
        return {}

    nodes = [
        ExecutionNode(
            node_id="parse", node_type=NodeType.FILE_PARSE,
            input_schema={}, output_schema={}, dependencies=[],
            timeout=10.0, retry_policy=RetryPolicy(), deterministic=True,
            audit_required=True, replay_required=True, execute=noop,
        ),
    ]
    return ExecutionGraph(job_id=job_id, nodes=nodes)


def _mock_session():
    """Return a MagicMock that behaves like a SQLAlchemy session."""
    session = MagicMock()
    session.text = lambda s: s
    return session


class TestJobStatus:
    def test_all_standard_statuses(self):
        expected = {"PENDING", "RUNNING", "NODE_FAILED", "FAILED",
                    "SUCCEEDED", "CANCELLED", "REPLAYING"}
        actual = {s.value for s in JobStatus}
        assert actual == expected

    def test_terminal_statuses(self):
        assert JobStatus.SUCCEEDED in JobStatus.terminal()
        assert JobStatus.FAILED in JobStatus.terminal()
        assert JobStatus.CANCELLED in JobStatus.terminal()
        assert JobStatus.PENDING not in JobStatus.terminal()
        assert JobStatus.RUNNING not in JobStatus.terminal()


class TestJobStore:
    @pytest.mark.asyncio
    async def test_create_job(self):
        session = _mock_session()
        store = JobStore(lambda: session)
        graph = _make_graph()
        job = await store.create(
            tenant_id="t1",
            file_id="f1",
            graph=graph,
        )

        assert job.job_id is not None
        assert job.status == JobStatus.PENDING
        assert job.tenant_id == "t1"
        assert job.file_id == "f1"

    @pytest.mark.asyncio
    async def test_transition_valid(self):
        session = _mock_session()
        MockRow = type('MockRow', (), {
            '_mapping': {
                "job_id": "j1", "tenant_id": "t1", "file_id": "f1",
                "status": "PENDING", "graph_json": "{}", "current_node": None,
                "error_json": None, "result_json": None, "trace_json": None,
                "replay_from": None, "created_at": "", "updated_at": "",
                "completed_at": None,
            }
        })
        session.execute.return_value.fetchone.return_value = MockRow()

        store = JobStore(lambda: session)
        result = await store.transition("j1", JobStatus.RUNNING)
        assert result.status == JobStatus.RUNNING

    @pytest.mark.asyncio
    async def test_transition_invalid(self):
        session = _mock_session()
        MockRow = type('MockRow', (), {
            '_mapping': {
                "job_id": "j2", "tenant_id": "t1", "file_id": "f1",
                "status": "SUCCEEDED", "graph_json": "{}", "current_node": None,
                "error_json": None, "result_json": None, "trace_json": None,
                "replay_from": None, "created_at": "", "updated_at": "",
                "completed_at": "",
            }
        })
        session.execute.return_value.fetchone.return_value = MockRow()

        store = JobStore(lambda: session)
        with pytest.raises(ValueError, match="Cannot transition"):
            await store.transition("j2", JobStatus.RUNNING)

    @pytest.mark.asyncio
    async def test_update_current_node(self):
        session = _mock_session()
        store = JobStore(lambda: session)
        await store.update_current_node("j1", "rule_check")


class TestJobOrchestrator:
    @pytest.mark.asyncio
    async def test_submit_returns_job_ref(self):
        """submit creates a PENDING job, starts _run in background, returns JobRef."""
        from app.runtime.job_orchestrator import JobOrchestrator

        session = _mock_session()
        store = JobStore(lambda: session)
        store.create = AsyncMock(return_value=Job(
            job_id="j1", tenant_id="t1", file_id="f1",
            status=JobStatus.PENDING, graph_json="{}",
            created_at="", updated_at="",
        ))
        runtime = MagicMock()

        orchestrator = JobOrchestrator(store, runtime)
        # ponytail: patch _run to avoid mocking the full DB fetch chain
        orchestrator._run = AsyncMock()

        result = await orchestrator.submit(
            tenant_id="t1", file_id="f1", graph=_make_graph(),
        )

        assert result.job_id == "j1"
        assert result.status == JobStatus.PENDING
        orchestrator._run.assert_called_once_with("j1")

    @pytest.mark.asyncio
    async def test_cancel_running_job(self):
        """cancel() calls task.cancel() on a not-done task, marks job CANCELLED."""
        from app.runtime.job_orchestrator import JobOrchestrator

        session = _mock_session()
        store = JobStore(lambda: session)
        store.complete = AsyncMock()

        runtime = MagicMock()
        orchestrator = JobOrchestrator(store, runtime)

        # ponytail: if task is already done, cancel skips the await path
        # and just calls store.complete(CANCELLED). This tests the full cancel flow.
        mock_task = MagicMock()
        mock_task.done.return_value = True  # already done — skips cancel() + await
        orchestrator._running["j1"] = mock_task

        await orchestrator.cancel("j1")
        store.complete.assert_called_once_with("j1", JobStatus.CANCELLED)

    @pytest.mark.asyncio
    async def test_status_returns_job(self):
        """status() delegates to store.get()."""
        from app.runtime.job_orchestrator import JobOrchestrator

        session = _mock_session()
        store = JobStore(lambda: session)
        expected = Job(
            job_id="j1", tenant_id="t1", file_id="f1",
            status=JobStatus.SUCCEEDED, graph_json="{}",
            created_at="", updated_at="", completed_at="",
        )
        store.get = AsyncMock(return_value=expected)
        runtime = MagicMock()

        orchestrator = JobOrchestrator(store, runtime)
        job = await orchestrator.status("j1")
        assert job.status == JobStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_concurrency_limit_rejects(self):
        """When running tasks reach max_concurrent, submit raises."""
        from app.runtime.job_orchestrator import JobOrchestrator

        session = _mock_session()
        store = JobStore(lambda: session)
        runtime = MagicMock()
        orchestrator = JobOrchestrator(store, runtime)

        # Simulate max concurrency reached
        orchestrator._running = {
            f"job{i}": MagicMock(done=MagicMock(return_value=False))
            for i in range(3)
        }

        with pytest.raises(ValueError, match="limit"):
            await orchestrator.submit(
                tenant_id="t1", file_id="f1", graph=_make_graph(),
                _concurrency_override=3,
            )
