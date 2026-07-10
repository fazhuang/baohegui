"""Tests for JobStore and JobOrchestrator."""
import pytest
from unittest.mock import MagicMock
from app.runtime.job_models import JobStatus, Job
from app.runtime.job_store import JobStore
from app.runtime.node_types import NodeType
from app.runtime.execution_node import ExecutionNode, RetryPolicy
from app.runtime.execution_graph import ExecutionGraph


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
        # Mock fetchone to return a PENDING job row
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
        # should not raise
