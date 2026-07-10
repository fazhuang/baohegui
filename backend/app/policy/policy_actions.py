"""Policy actions that the PolicyEvaluator can emit."""
from enum import Enum


class PolicyAction(str, Enum):
    # Risk escalation — only escalate, never de-escalate
    ESCALATE_TO_YELLOW = "escalate_to_yellow"
    ESCALATE_TO_RED = "escalate_to_red"

    # Review behavior
    REQUIRE_HUMAN_REVIEW = "require_human_review"
    SKIP_LLM_FOR_INDUSTRY = "skip_llm_for_industry"

    # Rule adjustments
    ADD_EXTRA_RULES = "add_extra_rules"
    WEAKEN_RULE_THRESHOLD = "weaken_rule_threshold"

    # Report
    SUPPRESS_FINDING_IN_REPORT = "suppress_finding_in_report"
    ADD_TENANT_DISCLAIMER = "add_tenant_disclaimer"
