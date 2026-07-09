-- audit_trace_schema.sql
-- Stores the full replayable audit trace alongside each compliance report.
-- The audit_trace JSON column holds the serialized AuditTrace (steps + hash chain).
-- This is write-once, append-never: one trace per report_id.

-- Migration to add audit_trace column to compliance_reports.
-- Run: ALTER TABLE compliance_reports ADD COLUMN IF NOT EXISTS ... (PostgreSQL)

-- ═══════════════════════════════════════════════════════════════
-- Column addition (idempotent)
-- ═══════════════════════════════════════════════════════════════

-- Add audit_trace column to compliance_reports (JSONB for queryability).
-- Stores the full AuditTrace.to_dict() output: steps[], root_hash,
-- terminal_hash, decision_hash, schema_version, file_hash, file_name.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'compliance_reports'
          AND column_name = 'audit_trace'
    ) THEN
        ALTER TABLE compliance_reports
        ADD COLUMN audit_trace JSONB;
    END IF;
END $$;

-- Add audit_trace_valid column (boolean — result of verify_replay at write time).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'compliance_reports'
          AND column_name = 'audit_trace_valid'
    ) THEN
        ALTER TABLE compliance_reports
        ADD COLUMN audit_trace_valid BOOLEAN DEFAULT NULL;
    END IF;
END $$;

-- ═══════════════════════════════════════════════════════════════
-- Indexes
-- ═══════════════════════════════════════════════════════════════

-- Look up by decision_hash across reports
CREATE INDEX IF NOT EXISTS idx_compliance_reports_decision_hash
    ON compliance_reports(decision_hash)
    WHERE decision_hash IS NOT NULL;

-- Find reports with invalid/legacy traces
CREATE INDEX IF NOT EXISTS idx_compliance_reports_trace_valid
    ON compliance_reports(audit_trace_valid, decision_integrity_status)
    WHERE audit_trace_valid IS NOT NULL;

-- ═══════════════════════════════════════════════════════════════
-- View: replayable_reports
-- ═══════════════════════════════════════════════════════════════

-- Reports that pass both PolicyKernel trace verification and full pipeline
-- hash-chain verification. These are fully replayable.
CREATE OR REPLACE VIEW replayable_reports AS
SELECT
    id,
    file_id,
    total_score,
    decision_action,
    decision_risk_level,
    decision_hash,
    decision_integrity_status,
    audit_trace_valid,
    created_at
FROM compliance_reports
WHERE decision_integrity_status = 'verified'
  AND audit_trace_valid = TRUE;

-- ═══════════════════════════════════════════════════════════════
-- audit_trace JSONB structure (documentation)
-- ═══════════════════════════════════════════════════════════════

-- {
--   "steps": [
--     {
--       "step": "input",
--       "input_snapshot": {...},      -- file_hash, sections, budget, etc.
--       "output_snapshot": {...},      -- same as input for step 0
--       "input_hash": "<sha256>",
--       "output_hash": "<sha256>"
--     },
--     {
--       "step": "routing",
--       "input_snapshot": null,        -- implicit: prev step's output
--       "output_snapshot": {...},      -- RoutingResult as dict
--       "input_hash": "<sha256>",
--       "output_hash": "<sha256>"
--     },
--     {
--       "step": "rule_engine",
--       ...                            -- violation counts + scores
--     },
--     {
--       "step": "parameter_bias",
--       ...
--     },
--     {
--       "step": "llm",
--       ...                            -- snapshot only (non-deterministic)
--     },
--     {
--       "step": "decision_input",
--       ...                            -- full DecisionInput snapshot
--     },
--     {
--       "step": "policy_decision",
--       ...                            -- full PolicyDecision snapshot
--     }
--   ],
--   "root_hash": "<sha256>",
--   "terminal_hash": "<sha256>",
--   "decision_hash": "<sha256>",
--   "schema_version": "2.1.0",
--   "file_hash": "<sha256>",
--   "file_name": "招标文件.pdf"
-- }
