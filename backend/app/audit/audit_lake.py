"""AuditLake — immutable audit event store with hash-chain validation.

ponytail: raw SQL like JobStore. Audit events are append-only — no updates, no deletes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.audit.audit_models import AuditEvent


class AuditLake:
    """Append-only audit event store.

    Audit events are written once and never modified. The hash chain
    (previous_hash → output_hash) can be verified across the full job.
    """

    def __init__(self, db_session_factory: Any) -> None:
        self._db_factory = db_session_factory

    async def record_event(
        self,
        job_id: str,
        node_id: str,
        node_type: str,
        sequence: int,
        input_hash: str,
        output_hash: str,
        previous_hash: str,
        *,
        actor: str = "system",
        tenant_id: str = "",
        parser_version: str = "",
        ocr_version: str = "",
        engine_version: str = "",
        error: str | None = None,
        duration_ms: int = 0,
    ) -> AuditEvent:
        """Append a single audit event. Returns the created event."""
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        db = self._db_factory()
        try:
            db.execute(
                db.text(
                    """INSERT INTO audit_events
                       (event_id, job_id, node_id, node_type, sequence,
                        input_hash, output_hash, previous_hash,
                        actor, tenant_id, parser_version, ocr_version, engine_version,
                        error, duration_ms, created_at)
                       VALUES (:eid, :jid, :nid, :nt, :seq,
                        :ih, :oh, :ph,
                        :a, :tid, :pv, :ov, :ev,
                        :err, :dms, :ca)"""
                ),
                {
                    "eid": event_id,
                    "jid": job_id,
                    "nid": node_id,
                    "nt": node_type,
                    "seq": sequence,
                    "ih": input_hash,
                    "oh": output_hash,
                    "ph": previous_hash,
                    "a": actor,
                    "tid": tenant_id,
                    "pv": parser_version,
                    "ov": ocr_version,
                    "ev": engine_version,
                    "err": error,
                    "dms": duration_ms,
                    "ca": now,
                },
            )
            db.commit()
        finally:
            db.close()

        return AuditEvent(
            event_id=event_id,
            job_id=job_id,
            node_id=node_id,
            node_type=node_type,
            sequence=sequence,
            input_hash=input_hash,
            output_hash=output_hash,
            previous_hash=previous_hash,
            actor=actor,
            tenant_id=tenant_id,
            parser_version=parser_version,
            ocr_version=ocr_version,
            engine_version=engine_version,
            error=error,
            duration_ms=duration_ms,
            created_at=now,
        )

    async def record_events(self, events: list[dict]) -> list[AuditEvent]:
        """Batch record audit events."""
        return [await self.record_event(**e) for e in events]

    async def get_chain(self, job_id: str) -> list[AuditEvent]:
        """Get the full audit chain for a job, ordered by sequence."""
        db = self._db_factory()
        try:
            rows = db.execute(
                db.text(
                    """SELECT * FROM audit_events
                       WHERE job_id = :jid
                       ORDER BY sequence"""
                ),
                {"jid": job_id},
            ).fetchall()
        finally:
            db.close()

        return [self._event_from_row(r) for r in rows]

    async def get_chain_validated(self, job_id: str) -> dict:
        """Get the audit chain and validate the hash chain.

        Returns {"events": [...], "chain_intact": bool, "broken_at": int | None}
        where broken_at is the sequence number where the chain breaks (None if intact).
        """
        events = await self.get_chain(job_id)
        chain_intact = True
        broken_at: int | None = None

        for i, event in enumerate(events):
            if i == 0:
                continue
            # Each event's previous_hash must match the prior event's output_hash
            if event.previous_hash != events[i - 1].output_hash:
                chain_intact = False
                broken_at = event.sequence
                break

        return {
            "events": [e.__dict__ for e in events],
            "chain_intact": chain_intact,
            "broken_at": broken_at,
        }

    async def get_by_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> list[AuditEvent]:
        """Get audit events for a tenant, latest first."""
        db = self._db_factory()
        try:
            rows = db.execute(
                db.text(
                    """SELECT * FROM audit_events
                       WHERE tenant_id = :tid
                       ORDER BY created_at DESC
                       LIMIT :lim OFFSET :off"""
                ),
                {"tid": tenant_id, "lim": limit, "off": offset},
            ).fetchall()
        finally:
            db.close()

        return [self._event_from_row(r) for r in rows]

    # ── Internal ─────────────────────────────────────────────

    @staticmethod
    def _event_from_row(row: Any) -> AuditEvent:
        d = dict(row._mapping)
        return AuditEvent(
            event_id=d["event_id"],
            job_id=d["job_id"],
            node_id=d["node_id"],
            node_type=d["node_type"],
            sequence=d["sequence"],
            input_hash=d["input_hash"],
            output_hash=d["output_hash"],
            previous_hash=d["previous_hash"],
            actor=d.get("actor", "system"),
            tenant_id=d.get("tenant_id", ""),
            parser_version=d.get("parser_version", ""),
            ocr_version=d.get("ocr_version", ""),
            engine_version=d.get("engine_version", ""),
            error=d.get("error"),
            duration_ms=d.get("duration_ms", 0),
            created_at=str(d.get("created_at", "")),
        )
