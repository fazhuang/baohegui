"""PolicyDefinition model — a single declarative policy rule."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.policy.policy_actions import PolicyAction


@dataclass
class PolicyDefinition:
    """A single declarative policy rule.

    Policies are evaluated by PolicyEvaluator against a PolicyContext.
    Matched policies produce PolicyActions that feed into PolicyKernel.
    """

    policy_id: str
    policy_type: str  # UX | TENANT | PLATFORM
    scope: str  # global | tenant:{id} | industry:{code}
    priority: int
    condition: dict[str, Any]  # ConditionalExpressionEngine-compatible
    action: PolicyAction
    effective_from: datetime
    expires_at: datetime | None = None
    approved_by: str = ""
    version: int = 1

    def is_effective(self) -> bool:
        """Policy is currently in effect."""
        now = datetime.now(timezone.utc)
        if now < self.effective_from:
            return False
        if self.expires_at and now >= self.expires_at:
            return False
        return True

    def is_expired(self) -> bool:
        """Policy has passed its expiration."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at
