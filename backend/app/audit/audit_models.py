"""Audit & Evidence models — AuditEvent, EvidenceRecord, EvidenceLink."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class EvidenceRecord:
    """A single evidence fragment extracted from a document.

    Stores only the snippet (tens of characters), not the full document.
    Full documents live in MinIO, referenced by source_file.
    """

    evidence_hash: str
    evidence_text: str
    source_file: str
    page: int = 0
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    block_ids: list[int] = field(default_factory=list)
    confidence: float = 1.0
    parser_version: str = ""
    ocr_version: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "evidence_hash": self.evidence_hash,
            "evidence_text": self.evidence_text[:200],
            "source_file": self.source_file,
            "page": self.page,
            "bbox": list(self.bbox),
            "block_ids": self.block_ids,
            "confidence": self.confidence,
            "parser_version": self.parser_version,
            "ocr_version": self.ocr_version,
        }


@dataclass
class EvidenceLink:
    """Links an evidence fragment to a finding within a job."""

    evidence_hash: str
    finding_id: str
    job_id: str
    created_at: str = ""


@dataclass
class AuditEvent:
    """A single node execution event in the audit chain."""

    event_id: str
    job_id: str
    node_id: str
    node_type: str
    sequence: int
    input_hash: str
    output_hash: str
    previous_hash: str
    actor: str = "system"
    tenant_id: str = ""
    parser_version: str = ""
    ocr_version: str = ""
    engine_version: str = ""
    error: str | None = None
    duration_ms: int = 0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
