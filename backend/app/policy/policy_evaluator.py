"""PolicyEvaluator — evaluates PolicyDefinitions against a PolicyContext to produce PolicyActions."""
from __future__ import annotations

from dataclasses import dataclass

from app.policy.policy_actions import PolicyAction
from app.policy.policy_definition import PolicyDefinition


@dataclass
class PolicyContext:
    """Context provided to PolicyEvaluator for matching policy conditions."""

    tenant_id: str
    industry: str
    budget: float

    # ponytail: dict-style access so condition matching is declarative
    def __getitem__(self, key: str):
        return getattr(self, key)

    def get(self, key: str, default=None):
        return getattr(self, key, default)


# ponytail: simple conditional evaluator — reuses the existing engine pattern
# without importing ConditionalExpressionEngine to avoid coupling
def _eval_condition(condition: dict, context: PolicyContext) -> bool:
    """Evaluate a single condition dict against the context. Returns True if matched."""
    if not condition:
        return True  # empty condition matches everything

    field = condition.get("field", "")
    op = condition.get("op", "")
    value = condition.get("value")

    ctx_value = context.get(field)
    if ctx_value is None:
        return False

    if op == "gte":
        return ctx_value >= value
    elif op == "gt":
        return ctx_value > value
    elif op == "lte":
        return ctx_value <= value
    elif op == "lt":
        return ctx_value < value
    elif op == "eq" or op == "==":
        return ctx_value == value
    elif op == "neq" or op == "!=":
        return ctx_value != value
    elif op == "in":
        return ctx_value in value

    return False


class PolicyEvaluator:
    """Evaluates all active policies in priority order, producing a list of PolicyActions.

    Reuses the existing ConditionalExpressionEngine pattern without coupling to it.
    """

    def __init__(self, policies: list[PolicyDefinition]) -> None:
        self._policies = sorted(policies, key=lambda p: p.priority)

    def evaluate(self, context: PolicyContext) -> list[PolicyAction]:
        """Evaluate all active policies against the context.

        Returns a deduplicated list of PolicyActions. On conflict (RED vs YELLOW),
        RED wins.
        """
        actions: list[PolicyAction] = []

        for policy in self._policies:
            if not policy.is_effective() or policy.is_expired():
                continue

            # Scope filtering
            if not self._scope_matches(policy.scope, context):
                continue

            # Condition matching
            if not _eval_condition(policy.condition, context):
                continue

            actions.append(policy.action)

        # Deduplicate, RED wins over YELLOW
        action_set = set(actions)
        if PolicyAction.ESCALATE_TO_RED in action_set:
            action_set.discard(PolicyAction.ESCALATE_TO_YELLOW)

        return sorted(action_set, key=lambda a: list(PolicyAction).index(a))

    @staticmethod
    def _scope_matches(scope: str, context: PolicyContext) -> bool:
        """Check if the policy scope applies to this context."""
        if scope == "global":
            return True
        if scope.startswith("tenant:") and scope == f"tenant:{context.tenant_id}":
            return True
        if scope.startswith("industry:") and scope == f"industry:{context.industry}":
            return True
        return False
