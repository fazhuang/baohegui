"""Tests for EvidenceLake and AuditLake."""
import pytest
from unittest.mock import MagicMock

from app.audit.audit_models import EvidenceRecord, AuditEvent


class TestEvidenceRecord:
    def test_to_dict_truncates_long_text(self):
        rec = EvidenceRecord(
            evidence_hash="abc123",
            evidence_text="x" * 300,
            source_file="test.pdf",
            page=3,
            bbox=(10, 20, 100, 200),
            block_ids=[1, 2],
            confidence=0.95,
            parser_version="1.0",
            ocr_version="2.0",
        )
        d = rec.to_dict()
        assert len(d["evidence_text"]) <= 200
        assert d["evidence_hash"] == "abc123"
        assert d["page"] == 3
        assert d["bbox"] == [10, 20, 100, 200]

    def test_defaults(self):
        rec = EvidenceRecord(
            evidence_hash="h", evidence_text="t", source_file="f"
        )
        assert rec.page == 0
        assert rec.bbox == (0, 0, 0, 0)
        assert rec.block_ids == []
        assert rec.confidence == 1.0


class TestAuditEvent:
    def test_created_at_auto_generated(self):
        event = AuditEvent(
            event_id="e1",
            job_id="j1",
            node_id="n1",
            node_type="RULE_CHECK",
            sequence=0,
            input_hash="ih",
            output_hash="oh",
            previous_hash="ph",
        )
        assert event.created_at != ""
        assert event.actor == "system"
        assert event.duration_ms == 0

    def test_all_fields(self):
        event = AuditEvent(
            event_id="e2",
            job_id="j2",
            node_id="n2",
            node_type="POLICY_KERNEL",
            sequence=1,
            input_hash="in",
            output_hash="out",
            previous_hash="prev",
            actor="admin",
            tenant_id="t1",
            parser_version="1.2",
            ocr_version="2.1",
            engine_version="3.0",
            error="timeout",
            duration_ms=5000,
        )
        assert event.tenant_id == "t1"
        assert event.parser_version == "1.2"
        assert event.error == "timeout"


class TestEvidenceLake:
    """Test EvidenceLake with mocked DB session."""

    @staticmethod
    def _make_session(fetchone_result=None, fetchall_result=None):
        session = MagicMock()
        mock_execute = session.execute.return_value
        mock_execute.fetchone.return_value = fetchone_result
        mock_execute.fetchall.return_value = fetchall_result or []
        return session

    @pytest.mark.asyncio
    async def test_store_new_evidence(self):
        from app.audit.evidence_lake import EvidenceLake, _evidence_key

        session = self._make_session(fetchone_result=None)
        lake = EvidenceLake(lambda: session)

        h = _evidence_key("本项目的资质要求为建筑一级")
        result = await lake.store(
            "本项目的资质要求为建筑一级",
            "test.pdf",
            page=1,
            bbox=(10, 20, 100, 200),
            parser_version="1.0",
        )
        assert result == h

    @pytest.mark.asyncio
    async def test_store_dedup(self):
        from app.audit.evidence_lake import EvidenceLake, _evidence_key

        h = _evidence_key("duplicate text")
        mock_row = MagicMock()
        mock_row._mapping = {"evidence_hash": h}
        session = self._make_session(fetchone_result=mock_row)
        lake = EvidenceLake(lambda: session)

        result = await lake.store("duplicate text", "test.pdf")
        assert result == h

    @pytest.mark.asyncio
    async def test_get_by_hash_found(self):
        from app.audit.evidence_lake import EvidenceLake

        row_data = {
            "evidence_hash": "h1",
            "evidence_text": "some text",
            "source_file": "f.pdf",
            "page": 5,
            "bbox": [1, 2, 3, 4],
            "block_ids": [10],
            "confidence": 0.9,
            "parser_version": "1",
            "ocr_version": "2",
            "created_at": "2026-01-01",
        }
        mock_row = MagicMock()
        mock_row._mapping = row_data
        session = self._make_session(fetchone_result=mock_row)
        lake = EvidenceLake(lambda: session)

        rec = await lake.get_by_hash("h1")
        assert rec is not None
        assert rec.evidence_hash == "h1"
        assert rec.page == 5

    @pytest.mark.asyncio
    async def test_get_by_hash_not_found(self):
        from app.audit.evidence_lake import EvidenceLake

        session = self._make_session(fetchone_result=None)
        lake = EvidenceLake(lambda: session)

        rec = await lake.get_by_hash("nope")
        assert rec is None

    @pytest.mark.asyncio
    async def test_get_by_finding(self):
        from app.audit.evidence_lake import EvidenceLake

        row_data = {
            "evidence_hash": "h2",
            "evidence_text": "text",
            "source_file": "f.pdf",
            "page": 1,
            "bbox": None,
            "block_ids": [],
            "confidence": 1.0,
            "parser_version": "",
            "ocr_version": "",
            "created_at": "",
        }
        mock_row = MagicMock()
        mock_row._mapping = row_data
        session = self._make_session(fetchall_result=[mock_row])
        lake = EvidenceLake(lambda: session)

        recs = await lake.get_by_finding("finding-1")
        assert len(recs) == 1
        assert recs[0].evidence_hash == "h2"


class TestAuditLake:
    """Test AuditLake with mocked DB session."""

    @staticmethod
    def _make_session(fetchone_result=None, fetchall_result=None):
        session = MagicMock()
        mock_execute = session.execute.return_value
        mock_execute.fetchone.return_value = fetchone_result
        mock_execute.fetchall.return_value = fetchall_result or []
        return session

    @pytest.mark.asyncio
    async def test_record_event(self):
        from app.audit.audit_lake import AuditLake

        session = self._make_session()
        lake = AuditLake(lambda: session)

        event = await lake.record_event(
            job_id="j1",
            node_id="n1",
            node_type="RULE_CHECK",
            sequence=0,
            input_hash="ih",
            output_hash="oh",
            previous_hash="root",
            tenant_id="t1",
            duration_ms=100,
        )
        assert event.job_id == "j1"
        assert event.node_type == "RULE_CHECK"
        assert event.sequence == 0
        assert event.event_id != ""

    @pytest.mark.asyncio
    async def test_chain_intact(self):
        from app.audit.audit_lake import AuditLake

        row1 = MagicMock()
        row1._mapping = {
            "event_id": "e1", "job_id": "j1", "node_id": "n1",
            "node_type": "FILE_PARSE", "sequence": 0,
            "input_hash": "root", "output_hash": "h1",
            "previous_hash": "root",
            "actor": "system", "tenant_id": "t1",
            "parser_version": "", "ocr_version": "", "engine_version": "",
            "error": None, "duration_ms": 50, "created_at": "2026-01-01",
        }
        row2 = MagicMock()
        row2._mapping = {
            "event_id": "e2", "job_id": "j1", "node_id": "n2",
            "node_type": "RULE_CHECK", "sequence": 1,
            "input_hash": "h1", "output_hash": "h2",
            "previous_hash": "h1",
            "actor": "system", "tenant_id": "t1",
            "parser_version": "", "ocr_version": "", "engine_version": "",
            "error": None, "duration_ms": 100, "created_at": "2026-01-01",
        }
        session = self._make_session(fetchall_result=[row1, row2])
        lake = AuditLake(lambda: session)

        result = await lake.get_chain_validated("j1")
        assert result["chain_intact"] is True
        assert result["broken_at"] is None
        assert len(result["events"]) == 2

    @pytest.mark.asyncio
    async def test_chain_broken(self):
        from app.audit.audit_lake import AuditLake

        row1 = MagicMock()
        row1._mapping = {
            "event_id": "e1", "job_id": "j1", "node_id": "n1",
            "node_type": "FILE_PARSE", "sequence": 0,
            "input_hash": "root", "output_hash": "h1",
            "previous_hash": "root",
            "actor": "system", "tenant_id": "",
            "parser_version": "", "ocr_version": "", "engine_version": "",
            "error": None, "duration_ms": 50, "created_at": "2026-01-01",
        }
        row2 = MagicMock()
        row2._mapping = {
            "event_id": "e2", "job_id": "j1", "node_id": "n2",
            "node_type": "LLM_CHECK", "sequence": 1,
            "input_hash": "h1", "output_hash": "h2",
            "previous_hash": "WRONG_HASH",
            "actor": "system", "tenant_id": "",
            "parser_version": "", "ocr_version": "", "engine_version": "",
            "error": None, "duration_ms": 80, "created_at": "2026-01-01",
        }
        session = self._make_session(fetchall_result=[row1, row2])
        lake = AuditLake(lambda: session)

        result = await lake.get_chain_validated("j1")
        assert result["chain_intact"] is False
        assert result["broken_at"] == 1

    @pytest.mark.asyncio
    async def test_empty_chain(self):
        from app.audit.audit_lake import AuditLake

        session = self._make_session(fetchall_result=[])
        lake = AuditLake(lambda: session)

        result = await lake.get_chain_validated("j1")
        assert result["chain_intact"] is True
        assert result["broken_at"] is None
        assert result["events"] == []
