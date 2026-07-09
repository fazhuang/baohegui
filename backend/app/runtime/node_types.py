"""Standard node types for the compliance check execution graph."""
from enum import Enum


class NodeType(str, Enum):
    """All registered node types in the compliance check pipeline."""

    FILE_PARSE = "FILE_PARSE"
    OCR = "OCR"
    TEXT_NORMALIZE = "TEXT_NORMALIZE"
    SECTION_SPLIT = "SECTION_SPLIT"
    RULE_CHECK = "RULE_CHECK"
    LLM_CHECK = "LLM_CHECK"
    FUSION = "FUSION"
    POLICY_KERNEL = "POLICY_KERNEL"
    EVIDENCE_MAPPING = "EVIDENCE_MAPPING"
    REPORT_BUILD = "REPORT_BUILD"
    FEEDBACK_SNAPSHOT = "FEEDBACK_SNAPSHOT"
