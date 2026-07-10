"""EvidenceLake — stores and deduplicates evidence fragments.

ponytail: raw SQL like JobStore. No SQLAlchemy model mapping.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.audit.audit_models import EvidenceRecord, EvidenceLink


def _evidence_key(text: str) -> str:
    """Deterministic hash of evidence text for dedup."""
    return hashlib.sha256(text.encode()).hexdigest()


class EvidenceLake:
    """Stores evidence fragments and links them to findings.

    Evidence is deduplicated by content hash — same text from different
    documents or findings shares one EvidenceRecord row.
    """

    def __init__(self, db_session_factory: Any) -> None:
        self._db_factory = db_session_factory

    async def store(
        self,
        evidence_text: str,
        source_file: str,
        *,
        page: int = 0,
        bbox: tuple[float, float, float, float] = (0, 0, 0, 0),
        block_ids: list[int] | None = None,
        confidence: float = 1.0,
        parser_version: str = "",
        ocr_version: str = "",
    ) -> str:
        """Store an evidence fragment. Returns its hash.
        Deduplicates: if the same text was already stored, returns existing hash.
        """
        evidence_hash = _evidence_key(evidence_text)
        now = datetime.now(timezone.utc).isoformat()

        db = self._db_factory()
        try:
            # Check for existing
            existing = db.execute(
                db.text(
                    "SELECT evidence_hash FROM evidence_records WHERE evidence_hash = :h"
                ),
                {"h": evidence_hash},
            ).fetchone()

            if existing is None:
                db.execute(
                    db.text(
                        """INSERT INTO evidence_records
                           (evidence_hash, evidence_text, source_file, page, bbox,
                            block_ids, confidence, parser_version, ocr_version, created_at)
                           VALUES (:h, :t, :sf, :p, :bb, :bi, :c, :pv, :ov, :ca)"""
                    ),
                    {
                        "h": evidence_hash,
                        "t": evidence_text[:5000],  # ponytail: truncate, not store full text
                        "sf": source_file,
                        "p": page,
                        "bb": list(bbox),
                        "bi": block_ids or [],
                        "c": confidence,
                        "pv": parser_version,
                        "ov": ocr_version,
                        "ca": now,
                    },
                )
                db.commit()
        finally:
            db.close()

        return evidence_hash

    async def link(
        self, evidence_hash: str, finding_id: str, job_id: str
    ) -> None:
        """Link an evidence fragment to a finding."""
        now = datetime.now(timezone.utc).isoformat()
        db = self._db_factory()
        try:
            db.execute(
                db.text(
                    """INSERT INTO evidence_links (evidence_hash, finding_id, job_id, created_at)
                       VALUES (:h, :f, :j, :ca)"""
                ),
                {"h": evidence_hash, "f": finding_id, "j": job_id, "ca": now},
            )
            db.commit()
        finally:
            db.close()

    async def store_many(
        self,
        fragments: list[dict],
        source_file: str,
        parser_version: str = "",
        ocr_version: str = "",
    ) -> list[str]:
        """Batch store evidence fragments. Returns list of hashes."""
        hashes = []
        for frag in fragments:
            h = await self.store(
                evidence_text=frag.get("text", ""),
                source_file=source_file,
                page=frag.get("page", 0),
                bbox=tuple(frag.get("bbox", (0, 0, 0, 0))),
                block_ids=frag.get("block_ids", []),
                confidence=frag.get("confidence", 1.0),
                parser_version=parser_version,
                ocr_version=ocr_version,
            )
            hashes.append(h)
        return hashes

    async def get_by_hash(self, evidence_hash: str) -> EvidenceRecord | None:
        """Retrieve a single evidence record by hash."""
        db = self._db_factory()
        try:
            row = db.execute(
                db.text(
                    "SELECT * FROM evidence_records WHERE evidence_hash = :h"
                ),
                {"h": evidence_hash},
            ).fetchone()
        finally:
            db.close()

        if row is None:
            return None
        return self._record_from_row(row)

    async def get_by_finding(self, finding_id: str) -> list[EvidenceRecord]:
        """Get all evidence linked to a finding."""
        db = self._db_factory()
        try:
            rows = db.execute(
                db.text(
                    """SELECT er.* FROM evidence_records er
                       JOIN evidence_links el ON er.evidence_hash = el.evidence_hash
                       WHERE el.finding_id = :fid
                       ORDER BY er.page"""
                ),
                {"fid": finding_id},
            ).fetchall()
        finally:
            db.close()

        return [self._record_from_row(r) for r in rows]

    async def get_by_job(self, job_id: str) -> list[EvidenceRecord]:
        """Get all evidence linked to a job."""
        db = self._db_factory()
        try:
            rows = db.execute(
                db.text(
                    """SELECT DISTINCT er.* FROM evidence_records er
                       JOIN evidence_links el ON er.evidence_hash = el.evidence_hash
                       WHERE el.job_id = :jid
                       ORDER BY er.page"""
                ),
                {"jid": job_id},
            ).fetchall()
        finally:
            db.close()

        return [self._record_from_row(r) for r in rows]

    # ── Internal ─────────────────────────────────────────────

    @staticmethod
    def _record_from_row(row: Any) -> EvidenceRecord:
        d = dict(row._mapping)
        bbox_raw = d.get("bbox")
        if isinstance(bbox_raw, (list, tuple)) and len(bbox_raw) == 4:
            bbox = tuple(bbox_raw)  # type: ignore[arg-type]
        else:
            bbox = (0.0, 0.0, 0.0, 0.0)

        return EvidenceRecord(
            evidence_hash=d["evidence_hash"],
            evidence_text=d.get("evidence_text", ""),
            source_file=d.get("source_file", ""),
            page=d.get("page", 0),
            bbox=bbox,
            block_ids=d.get("block_ids", []),
            confidence=d.get("confidence", 1.0),
            parser_version=d.get("parser_version", ""),
            ocr_version=d.get("ocr_version", ""),
            created_at=str(d.get("created_at", "")),
        )
