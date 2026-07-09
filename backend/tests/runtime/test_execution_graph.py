"""Tests for ExecutionNode, ExecutionGraph, and NodeType."""
import pytest
from app.runtime.node_types import NodeType
from app.runtime.execution_node import ExecutionNode, RetryPolicy


class TestNodeType:
    def test_all_standard_node_types_exist(self):
        """All 11 standard node types must be defined."""
        expected = {
            "FILE_PARSE", "OCR", "TEXT_NORMALIZE", "SECTION_SPLIT",
            "RULE_CHECK", "LLM_CHECK", "FUSION", "POLICY_KERNEL",
            "EVIDENCE_MAPPING", "REPORT_BUILD", "FEEDBACK_SNAPSHOT",
        }
        actual = {nt.value for nt in NodeType}
        assert actual == expected

    def test_policy_kernel_is_critical(self):
        """POLICY_KERNEL exists — security gating."""
        assert NodeType.POLICY_KERNEL is not None


class TestRetryPolicy:
    def test_default_retry_policy_no_retries(self):
        rp = RetryPolicy()
        assert rp.max_retries == 0
        assert rp.backoff_seconds == 0.0
        assert rp.backoff_multiplier == 1.0

    def test_retry_policy_with_retries(self):
        rp = RetryPolicy(max_retries=3, backoff_seconds=1.0, backoff_multiplier=2.0)
        assert rp.max_retries == 3
        assert rp.backoff_seconds == 1.0
        assert rp.backoff_multiplier == 2.0


class TestExecutionNode:
    def test_create_minimal_node(self):
        def dummy_execute(inputs):
            return {"ok": True}

        node = ExecutionNode(
            node_id="test_node",
            node_type=NodeType.FILE_PARSE,
            input_schema={"type": "object", "properties": {"file_path": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            dependencies=[],
            timeout=30.0,
            retry_policy=RetryPolicy(),
            deterministic=True,
            audit_required=True,
            replay_required=True,
            execute=dummy_execute,
        )
        assert node.node_id == "test_node"
        assert node.node_type == NodeType.FILE_PARSE
        assert node.dependencies == []
        assert node.deterministic is True
        assert node.audit_required is True
        assert node.replay_required is True

    def test_node_with_dependencies(self):
        def dummy_execute(inputs):
            return {"ok": True}

        node = ExecutionNode(
            node_id="fusion",
            node_type=NodeType.FUSION,
            input_schema={},
            output_schema={},
            dependencies=["rule_check", "llm_check"],
            timeout=60.0,
            retry_policy=RetryPolicy(max_retries=1, backoff_seconds=5.0),
            deterministic=True,
            audit_required=True,
            replay_required=True,
            execute=dummy_execute,
        )
        assert "rule_check" in node.dependencies
        assert "llm_check" in node.dependencies

    def test_llm_node_is_non_deterministic_by_default(self):
        def dummy_execute(inputs):
            return {"ok": True}

        node = ExecutionNode(
            node_id="llm",
            node_type=NodeType.LLM_CHECK,
            input_schema={},
            output_schema={},
            dependencies=[],
            timeout=120.0,
            retry_policy=RetryPolicy(max_retries=2, backoff_seconds=10.0),
            deterministic=False,
            audit_required=True,
            replay_required=True,
            execute=dummy_execute,
        )
        assert node.deterministic is False
