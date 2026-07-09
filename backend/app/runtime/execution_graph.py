"""ExecutionGraph -- a DAG representing one complete compliance check."""
from collections import deque
from dataclasses import dataclass

from app.runtime.execution_node import ExecutionNode


@dataclass
class ExecutionGraph:
    """A directed acyclic graph of ExecutionNodes for one compliance check job."""

    job_id: str
    nodes: list[ExecutionNode]

    def __post_init__(self) -> None:
        self._node_map: dict[str, ExecutionNode] = {}
        self.validate()

    def validate(self) -> None:
        """Validate the graph structure. Raises ValueError on failure."""
        # Check for duplicate node_ids
        seen: set[str] = set()
        for node in self.nodes:
            if node.node_id in seen:
                raise ValueError(f"Duplicate node_id: {node.node_id}")
            seen.add(node.node_id)
            self._node_map[node.node_id] = node

        # Check all dependency references exist
        for node in self.nodes:
            for dep in node.dependencies:
                if dep not in self._node_map:
                    raise ValueError(
                        f"Dependency '{dep}' not found in graph for node '{node.node_id}'"
                    )

        # Check for cycles via Kahn's algorithm
        self.topological_order()  # raises if cycle detected

    def topological_order(self) -> list[str]:
        """Return node_ids in topological order. Raises ValueError on cycle."""
        in_degree: dict[str, int] = {}
        adjacency: dict[str, list[str]] = {}

        for node in self.nodes:
            nid = node.node_id
            if nid not in in_degree:
                in_degree[nid] = 0
            if nid not in adjacency:
                adjacency[nid] = []
            for dep in node.dependencies:
                in_degree[nid] = in_degree.get(nid, 0) + 1
                adjacency.setdefault(dep, []).append(nid)
            # ensure all dependency nodes are tracked
            for dep in node.dependencies:
                if dep not in in_degree:
                    in_degree[dep] = 0
                if dep not in adjacency:
                    adjacency[dep] = []

        queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
        result: list[str] = []

        while queue:
            nid = queue.popleft()
            result.append(nid)
            for neighbor in adjacency.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(in_degree):
            raise ValueError(f"Cycle detected in execution graph: {set(in_degree) - set(result)}")

        return result

    def get_node(self, node_id: str) -> ExecutionNode:
        """Get a node by id. Raises KeyError if not found."""
        if not self._node_map:
            for node in self.nodes:
                self._node_map[node.node_id] = node
        return self._node_map[node_id]
