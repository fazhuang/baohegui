"""Tests for ExecutionRuntime."""
import asyncio
import pytest
from app.runtime.node_types import NodeType
from app.runtime.execution_node import ExecutionNode, RetryPolicy
from app.runtime.execution_graph import ExecutionGraph
from app.runtime.execution_runtime import ExecutionRuntime, NodeFailure


class TestExecutionRuntime:
    def _make_node(self, node_id, node_type, dependencies=None, execute_fn=None, **kwargs):
        if execute_fn is None:

            async def noop(inputs):
                return {"status": "ok", "from": node_id}

            execute_fn = noop
        if dependencies is None:
            dependencies = []

        defaults = dict(
            node_id=node_id,
            node_type=node_type,
            input_schema={},
            output_schema={},
            dependencies=dependencies,
            timeout=10.0,
            retry_policy=RetryPolicy(),
            deterministic=True,
            audit_required=True,
            replay_required=True,
            execute=execute_fn,
        )
        defaults.update(kwargs)
        return ExecutionNode(**defaults)

    @pytest.mark.asyncio
    async def test_execute_single_node(self):
        node = self._make_node("a", NodeType.FILE_PARSE)
        graph = ExecutionGraph(job_id="j1", nodes=[node])
        runtime = ExecutionRuntime()
        results = await runtime.execute(graph)

        assert "a" in results
        assert results["a"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_execute_linear_chain(self):
        shared = {}

        async def parse(inputs):
            shared["parsed"] = True
            return {"sections": {"title": "test"}}

        async def normalize(inputs):
            assert shared["parsed"]
            return {"text": "normalized"}

        nodes = [
            self._make_node("parse", NodeType.FILE_PARSE, execute_fn=parse),
            self._make_node("norm", NodeType.TEXT_NORMALIZE, dependencies=["parse"], execute_fn=normalize),
        ]
        graph = ExecutionGraph(job_id="j2", nodes=nodes)
        runtime = ExecutionRuntime()
        results = await runtime.execute(graph)

        assert results["parse"]["sections"] == {"title": "test"}
        assert results["norm"]["text"] == "normalized"

    @pytest.mark.asyncio
    async def test_execute_parallel_branches(self):
        execution_order = []

        async def rule(inputs):
            await asyncio.sleep(0.02)
            execution_order.append("rule")
            return {"rule": "ok"}

        async def llm(inputs):
            await asyncio.sleep(0.01)
            execution_order.append("llm")
            return {"llm": "ok"}

        async def fusion(inputs):
            execution_order.append("fusion")
            return {"fusion": "ok"}

        nodes = [
            self._make_node("split", NodeType.SECTION_SPLIT,
                            execute_fn=lambda i: {"sections": []}),
            self._make_node("rule", NodeType.RULE_CHECK, dependencies=["split"],
                            execute_fn=rule),
            self._make_node("llm", NodeType.LLM_CHECK, dependencies=["split"],
                            execute_fn=llm, deterministic=False),
            self._make_node("fusion", NodeType.FUSION, dependencies=["rule", "llm"],
                            execute_fn=fusion),
        ]
        graph = ExecutionGraph(job_id="j3", nodes=nodes)
        runtime = ExecutionRuntime()
        results = await runtime.execute(graph)

        # Both rule and llm finished before fusion
        assert execution_order[-1] == "fusion"
        assert "rule" in execution_order[:3]
        assert "llm" in execution_order[:3]

    @pytest.mark.asyncio
    async def test_node_failure_produces_node_failure_object(self):
        async def bad_node(inputs):
            raise ValueError("simulated failure")

        nodes = [
            self._make_node("bad", NodeType.RULE_CHECK, execute_fn=bad_node),
        ]
        graph = ExecutionGraph(job_id="j4", nodes=nodes)
        runtime = ExecutionRuntime()
        results = await runtime.execute(graph)

        assert "bad" in results
        assert isinstance(results["bad"], NodeFailure)
        assert "simulated failure" in results["bad"].error
        assert results["bad"].node_id == "bad"

    @pytest.mark.asyncio
    async def test_downstream_skipped_on_upstream_failure(self):
        async def fail(inputs):
            raise ValueError("upstream fail")

        execution_order = []

        async def downstream(inputs):
            execution_order.append("downstream")
            return {}

        nodes = [
            self._make_node("up", NodeType.FILE_PARSE, execute_fn=fail),
            self._make_node("down", NodeType.OCR, dependencies=["up"], execute_fn=downstream),
        ]
        graph = ExecutionGraph(job_id="j5", nodes=nodes)
        runtime = ExecutionRuntime()
        results = await runtime.execute(graph)

        assert isinstance(results["up"], NodeFailure)
        assert "down" not in execution_order  # never executed

    @pytest.mark.asyncio
    async def test_policy_kernel_failure_fails_entire_job(self):
        async def fail(inputs):
            raise ValueError("policy failure")

        async def upstream(inputs):
            return {"data": "ok"}

        nodes = [
            self._make_node("up", NodeType.FUSION, execute_fn=upstream),
            self._make_node("pk", NodeType.POLICY_KERNEL, dependencies=["up"], execute_fn=fail),
        ]
        graph = ExecutionGraph(job_id="j6", nodes=nodes)
        runtime = ExecutionRuntime()

        with pytest.raises(ValueError, match="policy failure"):
            await runtime.execute(graph, fail_fast_on_high_risk=True)

    @pytest.mark.asyncio
    async def test_on_step_callback(self):
        steps = []

        async def ok(inputs):
            return {"x": 1}

        nodes = [
            self._make_node("a", NodeType.FILE_PARSE, execute_fn=ok),
            self._make_node("b", NodeType.OCR, dependencies=["a"], execute_fn=ok),
        ]
        graph = ExecutionGraph(job_id="j7", nodes=nodes)
        runtime = ExecutionRuntime()

        async def on_step(node_id, status):
            steps.append((node_id, status))

        await runtime.execute(graph, on_step=on_step)
        assert len(steps) == 4  # 2 started + 2 completed
        node_ids = {s[0] for s in steps}
        assert node_ids == {"a", "b"}

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        call_count = {"count": 0}

        async def flaky(inputs):
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("transient error")
            return {"recovered": True}

        node = self._make_node(
            "flaky", NodeType.RULE_CHECK,
            execute_fn=flaky,
            retry_policy=RetryPolicy(max_retries=3, backoff_seconds=0.001),
        )
        graph = ExecutionGraph(job_id="j8", nodes=[node])
        runtime = ExecutionRuntime()
        results = await runtime.execute(graph)

        assert results["flaky"]["recovered"] is True
        assert call_count["count"] == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        call_count = {"count": 0}

        async def always_fail(inputs):
            call_count["count"] += 1
            raise ValueError("persistent error")

        node = self._make_node(
            "fail", NodeType.RULE_CHECK,
            execute_fn=always_fail,
            retry_policy=RetryPolicy(max_retries=2, backoff_seconds=0.001),
        )
        graph = ExecutionGraph(job_id="j9", nodes=[node])
        runtime = ExecutionRuntime()
        results = await runtime.execute(graph)

        assert isinstance(results["fail"], NodeFailure)
        assert call_count["count"] == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_timeout_kills_node(self):
        async def slow(inputs):
            await asyncio.sleep(5.0)
            return {}

        node = self._make_node("slow", NodeType.LLM_CHECK, execute_fn=slow, timeout=0.05)
        graph = ExecutionGraph(job_id="j10", nodes=[node])
        runtime = ExecutionRuntime()
        results = await runtime.execute(graph)

        assert isinstance(results["slow"], NodeFailure)
        assert "timeout" in results["slow"].error.lower() or "cancel" in results["slow"].error.lower()
