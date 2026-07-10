"""Tests for NodeContract and ContractRegistry."""
import pytest
from app.runtime.node_types import NodeType
from app.runtime.execution_node import ExecutionNode, RetryPolicy
from app.runtime.contract_registry import (
    NodeContract,
    SecurityLevel,
    ContractRegistry,
    ContractViolationError,
    UnregisteredNodeError,
)


class TestSecurityLevel:
    def test_levels_exist(self):
        assert SecurityLevel.STANDARD
        assert SecurityLevel.HIGH
        assert SecurityLevel.CRITICAL


class TestNodeContract:
    def test_create_contract(self):
        def dummy(inputs):
            return {}

        contract = NodeContract(
            node_type=NodeType.RULE_CHECK,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            cacheable=False,
            retryable=True,
            deterministic=True,
            replay_required=True,
            degradable=False,
            security_level=SecurityLevel.HIGH,
            execute_fn=dummy,
        )
        assert contract.node_type == NodeType.RULE_CHECK
        assert contract.degradable is False
        assert contract.security_level == SecurityLevel.HIGH


class TestContractRegistry:
    def test_registry_rejects_unregistered_node_type(self):
        registry = ContractRegistry({})

        def noop(i):
            return {}

        node = ExecutionNode(
            node_id="test", node_type=NodeType.LLM_CHECK,
            input_schema={}, output_schema={}, dependencies=[],
            timeout=10.0, retry_policy=RetryPolicy(), deterministic=False,
            audit_required=True, replay_required=True, execute=noop,
        )
        with pytest.raises(UnregisteredNodeError, match="not registered"):
            registry.validate_node(node)

    def test_registry_rejects_field_conflict(self):
        def dummy(inputs):
            return {}

        contract = NodeContract(
            node_type=NodeType.RULE_CHECK,
            input_schema={}, output_schema={},
            cacheable=False, retryable=True,
            deterministic=True,  # contract says must be deterministic
            replay_required=True, degradable=False,
            security_level=SecurityLevel.HIGH,
            execute_fn=dummy,
        )
        registry = ContractRegistry({NodeType.RULE_CHECK: contract})

        node = ExecutionNode(
            node_id="test", node_type=NodeType.RULE_CHECK,
            input_schema={}, output_schema={}, dependencies=[],
            timeout=10.0, retry_policy=RetryPolicy(),
            deterministic=False,  # conflicts with contract
            audit_required=True, replay_required=True,
            execute=dummy,
        )
        with pytest.raises(ContractViolationError, match="deterministic"):
            registry.validate_node(node)

    def test_registry_accepts_compliant_node(self):
        def dummy(inputs):
            return {}

        contract = NodeContract(
            node_type=NodeType.RULE_CHECK,
            input_schema={}, output_schema={},
            cacheable=False, retryable=True, deterministic=True,
            replay_required=True, degradable=False,
            security_level=SecurityLevel.HIGH,
            execute_fn=dummy,
        )
        registry = ContractRegistry({NodeType.RULE_CHECK: contract})

        node = ExecutionNode(
            node_id="test", node_type=NodeType.RULE_CHECK,
            input_schema={}, output_schema={}, dependencies=[],
            timeout=10.0, retry_policy=RetryPolicy(),
            deterministic=True, audit_required=True, replay_required=True,
            execute=dummy,
        )
        registry.validate_node(node)  # should not raise

    def test_validate_graph_rejects_unregistered(self):
        def dummy(inputs):
            return {}

        registry = ContractRegistry({})  # empty — nothing registered

        node = ExecutionNode(
            node_id="test", node_type=NodeType.OCR,
            input_schema={}, output_schema={}, dependencies=[],
            timeout=10.0, retry_policy=RetryPolicy(), deterministic=True,
            audit_required=True, replay_required=True, execute=dummy,
        )
        from app.runtime.execution_graph import ExecutionGraph
        graph = ExecutionGraph(job_id="j", nodes=[node])
        with pytest.raises(UnregisteredNodeError):
            registry.validate_graph(graph)

    def test_policy_kernel_is_critical_and_not_degradable(self):
        # The default contract registry must enforce these invariants
        from app.runtime.contracts import REGISTRY

        pk_contract = REGISTRY[NodeType.POLICY_KERNEL]
        assert pk_contract.security_level == SecurityLevel.CRITICAL
        assert pk_contract.degradable is False

    def test_rule_check_is_not_degradable(self):
        from app.runtime.contracts import REGISTRY

        rc_contract = REGISTRY[NodeType.RULE_CHECK]
        assert rc_contract.degradable is False
        assert rc_contract.deterministic is True

    def test_llm_check_is_degradable_and_non_deterministic(self):
        from app.runtime.contracts import REGISTRY

        llm_contract = REGISTRY[NodeType.LLM_CHECK]
        assert llm_contract.degradable is True
        assert llm_contract.deterministic is False

    def test_all_11_node_types_registered(self):
        from app.runtime.contracts import REGISTRY

        for nt in NodeType:
            assert nt in REGISTRY, f"NodeType.{nt.value} not registered"
