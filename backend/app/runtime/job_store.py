"""JobStore — PostgreSQL-backed job persistence with state machine enforcement."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.runtime.job_models import Job, JobStatus
from app.runtime.execution_graph import ExecutionGraph


class JobStore:
    """Persists jobs to PostgreSQL via SQLAlchemy session."""

    def __init__(self, db_session_factory: Any) -> None:
        """db_session_factory is a callable that yields a SQLAlchemy Session."""
        self._db_factory = db_session_factory

    async def create(
        self,
        tenant_id: str,
        file_id: str,
        graph: ExecutionGraph,
        replay_from: str | None = None,
    ) -> Job:
        """Create a new PENDING job."""
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        graph_json = json.dumps(
            {"job_id": graph.job_id, "nodes": [
                {
                    "node_id": n.node_id,
                    "node_type": n.node_type.value,
                    "dependencies": n.dependencies,
                    "deterministic": n.deterministic,
                }
                for n in graph.nodes
            ]},
            ensure_ascii=False,
        )

        db = self._db_factory()
        try:
            db.execute(
                db.text(
                    """INSERT INTO jobs (job_id, tenant_id, file_id, status, graph_json,
                       replay_from, created_at, updated_at)
                       VALUES (:job_id, :tenant_id, :file_id, :status, :graph_json,
                       :replay_from, :created_at, :updated_at)"""
                ),
                {
                    "job_id": job_id,
                    "tenant_id": tenant_id,
                    "file_id": file_id,
                    "status": JobStatus.PENDING.value,
                    "graph_json": graph_json,
                    "replay_from": replay_from,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            db.commit()
        finally:
            db.close()

        return Job(
            job_id=job_id,
            tenant_id=tenant_id,
            file_id=file_id,
            status=JobStatus.PENDING,
            graph_json=graph_json,
            replay_from=replay_from,
            created_at=now,
            updated_at=now,
        )

    async def get(self, job_id: str) -> Job:
        """Get a job by ID. Raises ValueError if not found."""
        db = self._db_factory()
        try:
            row = db.execute(
                db.text("SELECT * FROM jobs WHERE job_id = :job_id"),
                {"job_id": job_id},
            ).fetchone()
        finally:
            db.close()

        if row is None:
            raise ValueError(f"Job '{job_id}' not found")
        return self._job_from_row(row)

    async def transition(self, job_id: str, new_status: JobStatus) -> Job:
        """Transition a job to a new status. Enforces valid state transitions."""
        job = await self.get(job_id)
        current_status = job.status

        valid = JobStatus.valid_transitions().get(current_status, set())
        if new_status not in valid:
            raise ValueError(
                f"Cannot transition from {current_status.value} to {new_status.value}"
            )

        now = datetime.now(timezone.utc).isoformat()
        updates: dict[str, Any] = {"status": new_status.value, "updated_at": now}
        if new_status in JobStatus.terminal():
            updates["completed_at"] = now

        db = self._db_factory()
        try:
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            db.execute(
                db.text(f"UPDATE jobs SET {set_clause} WHERE job_id = :job_id"),
                {**updates, "job_id": job_id},
            )
            db.commit()
        finally:
            db.close()

        job.status = new_status
        for k, v in updates.items():
            setattr(job, k, v)
        return job

    async def update_current_node(self, job_id: str, node_id: str) -> None:
        """Update the currently executing node."""
        db = self._db_factory()
        try:
            db.execute(
                db.text(
                    "UPDATE jobs SET current_node = :node_id, updated_at = :now "
                    "WHERE job_id = :job_id"
                ),
                {
                    "node_id": node_id,
                    "now": datetime.now(timezone.utc).isoformat(),
                    "job_id": job_id,
                },
            )
            db.commit()
        finally:
            db.close()

    async def complete(
        self,
        job_id: str,
        final_status: JobStatus,
        result: dict[str, Any] | None = None,
        error: Exception | None = None,
        trace: Any | None = None,
    ) -> Job:
        """Complete a job with result or error."""
        now = datetime.now(timezone.utc).isoformat()

        updates: dict[str, Any] = {
            "status": final_status.value,
            "updated_at": now,
            "completed_at": now,
        }
        if result is not None:
            updates["result_json"] = json.dumps(result, default=str, ensure_ascii=False)
        if error is not None:
            updates["error_json"] = json.dumps(
                {"type": type(error).__name__, "message": str(error)},
                ensure_ascii=False,
            )
        if trace is not None:
            updates["trace_json"] = json.dumps(
                {"steps": [
                    {"node_id": s.node_id, "node_type": s.node_type.value,
                     "input_hash": s.input_hash, "output_hash": s.output_hash,
                     "previous_hash": s.previous_hash}
                    for s in trace.steps
                ]},
                ensure_ascii=False,
            )

        db = self._db_factory()
        try:
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            db.execute(
                db.text(f"UPDATE jobs SET {set_clause} WHERE job_id = :job_id"),
                {**updates, "job_id": job_id},
            )
            db.commit()
        finally:
            db.close()

        job = await self.get(job_id)
        return job

    # ponytail: manual row-to-dict instead of depending on SQLAlchemy model mapping
    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a SQLAlchemy Row to a plain dict."""
        return dict(row._mapping)

    @staticmethod
    def _job_from_row(row: Any) -> Job:
        d = JobStore._row_to_dict(row)
        return JobStore._job_from_dict(d)

    @staticmethod
    def _job_from_dict(d: dict[str, Any]) -> Job:
        return Job(
            job_id=d["job_id"],
            tenant_id=d["tenant_id"],
            file_id=d["file_id"],
            status=JobStatus(d["status"]),
            graph_json=d.get("graph_json", "{}"),
            current_node=d.get("current_node"),
            error_json=d.get("error_json") if d.get("error_json") else None,
            result_json=d.get("result_json") if d.get("result_json") else None,
            trace_json=d.get("trace_json") if d.get("trace_json") else None,
            replay_from=d.get("replay_from"),
            created_at=str(d.get("created_at", "")),
            updated_at=str(d.get("updated_at", "")),
            completed_at=str(d.get("completed_at")) if d.get("completed_at") else None,
        )
