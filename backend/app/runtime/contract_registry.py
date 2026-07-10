"""Node Contract Registry — prevents unregistered nodes from entering the Runtime."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from collections.abc import Callable
from typing import Any

from app.runtime.node_types import NodeType
from app.runtime.execution_node import ExecutionNode
from app.runtime.execution_graph import ExecutionGraph


class SecurityLevel(str, Enum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class NodeContract:
    """Contract that every node of a given NodeType must satisfy."""

    node_type: NodeType
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    cacheable: bool
    retryable: bool
    deterministic: bool
    replay_required: bool
    degradable: bool
    security_level: SecurityLevel
    execute_fn: Callable[..., Any]


class ContractViolationError(ValueError):
    """Raised when a node violates its contract."""


class UnregisteredNodeError(ValueError):
    """Raised when a node type is not in the contract registry."""


class ContractRegistry:
    """Centralized registry of NodeContracts. Validates nodes at graph-build and execute time."""

    def __init__(self, contracts: dict[NodeType, NodeContract]) -> None:
        self._contracts = contracts

    def get(self, node_type: NodeType) -> NodeContract:
        if node_type not in self._contracts:
            raise UnregisteredNodeError(f"NodeType '{node_type.value}' is not registered")
        return self._contracts[node_type]

    def validate_node(self, node: ExecutionNode) -> None:
        """Validate a single node against its contract. Raises on violation."""
        contract = self.get(node.node_type)

        # Deterministic must match
        if contract.deterministic and not node.deterministic:
            raise ContractViolationError(
                f"Node '{node.node_id}': contract requires deterministic=True, "
                f"got deterministic=False"
            )

        # Replay required must match
        if contract.replay_required and not node.replay_required:
            raise ContractViolationError(
                f"Node '{node.node_id}': contract requires replay_required=True"
            )

    def validate_graph(self, graph: ExecutionGraph) -> None:
        """Validate all nodes in a graph. Raises on first violation."""
        for node in graph.nodes:
            self.validate_node(node)

    def validate_all(self) -> None:
        """Startup-time validation: all registered contracts have valid execute_fn."""
        for node_type, contract in self._contracts.items():
            if contract.execute_fn is None:
                raise ContractViolationError(
                    f"Contract for NodeType '{node_type.value}' has no execute_fn"
                )
            if not callable(contract.execute_fn):
                raise ContractViolationError(
                    f"Contract for NodeType '{node_type.value}' has non-callable execute_fn"
                )
