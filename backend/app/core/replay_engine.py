"""Replay Engine — deterministic end-to-end audit trail for the compliance pipeline.

Pipeline: input → routing → rule_engine → parameter_bias → llm → decision_input → policy_decision

Each step stores input_snapshot + output_snapshot + hash(prev_hash || canonical(output)).
The LLM step is captured (non-deterministic); all other steps are deterministic.

Replay verifies: given the stored snapshots, re-running deterministic steps produces
identical output. PolicyKernel's own trace_chain covers the policy→decision segment.

Usage:
    # After pipeline runs:
    trace = AuditTrace.from_pipeline(...)
    trace.verify_chain()  # → {"valid": True, ...}

    # Later, from stored trace:
    replayed = replay_decision(trace)
    assert replayed.decision_hash == trace.decision_hash
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from app.core.policy_kernel import (
    DecisionInput,
    PolicyDecision,
    _canonical_json,
    policy_kernel,
    sha256_hex,
    verify_trace,
)


# ═══════════════════════════════════════════════════════════════
# Step snapshot
# ═══════════════════════════════════════════════════════════════

@dataclass
class StepSnapshot:
    """One step in the pipeline trace with hash chain links."""
    step: str                                    # pipeline step name
    input_snapshot: dict | None = None            # canonical input
    output_snapshot: dict | None = None           # canonical output
    input_hash: str = ""                          # SHA-256 of input_snapshot (step 0) or prev output_hash
    output_hash: str = ""                         # SHA-256(prev_hash || canonical(output_snapshot))

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "input_snapshot": self.input_snapshot,
            "output_snapshot": self.output_snapshot,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StepSnapshot":
        return cls(**d)


# ═══════════════════════════════════════════════════════════════
# AuditTrace
# ═══════════════════════════════════════════════════════════════

class AuditTrace:
    """Full pipeline audit trace with hash chain.

    The hash chain links all pipeline steps. The terminal hash is the
    PolicyDecision.decision_hash, which itself has an internal 5-layer trace.
    """

    steps: list[StepSnapshot]
    root_hash: str
    terminal_hash: str
    decision_hash: str
    schema_version: str
    file_hash: str
    file_name: str

    def __init__(self):
        self.steps = []
        self.root_hash = ""
        self.terminal_hash = ""
        self.decision_hash = ""
        self.schema_version = ""
        self.file_hash = ""
        self.file_name = ""

    @classmethod
    def from_pipeline(
        cls,
        *,
        file_hash: str = "",
        file_name: str = "",
        parsed_sections: dict[str, str] | None = None,
        budget: float | None = None,
        procurement_method: str = "",
        project_type: str = "",
        industries: list[str] | None = None,
        platform: str | None = None,
        routing_result: Any | None = None,
        rule_result: Any | None = None,
        bias_result: Any | None = None,
        llm_result: Any | None = None,
        decision_input: DecisionInput | None = None,
        policy_decision: PolicyDecision | None = None,
    ) -> "AuditTrace":
        """Build trace from post-pipeline snapshots.

        Call this after the full pipeline has run. Pass all intermediate results.
        The LLM step is captured as-is (non-deterministic).
        """
        if policy_decision is None:
            raise ValueError("policy_decision is required")
        if decision_input is None:
            raise ValueError("decision_input is required")

        trace = cls()
        trace.file_hash = file_hash
        trace.file_name = file_name
        trace.schema_version = policy_decision.schema_version
        trace.decision_hash = policy_decision.decision_hash

        sections = parsed_sections or {}
        prev_hash = ""

        # ── Step 0: input ──────────────────────────────────────
        inp = _canonical_for_step({
            "file_hash": file_hash,
            "file_name": file_name,
            "section_count": len(sections),
            "section_names": sorted(sections.keys()),
            "section_lengths": {k: len(v) for k, v in sorted(sections.items())},
            "budget": budget,
            "procurement_method": procurement_method,
            "project_type": project_type,
            "industries": sorted(industries) if industries else None,
            "platform": platform,
        })
        h = sha256_hex(_canonical_json(inp))
        step = StepSnapshot(step="input", input_snapshot=inp, output_snapshot=inp,
                            input_hash=h, output_hash=sha256_hex(h.encode() + _canonical_json(inp)))
        trace.root_hash = h
        prev_hash = step.output_hash
        trace.steps.append(step)

        # ── Step 1: routing ────────────────────────────────────
        rout = routing_result.model_dump(mode="json") if routing_result else {}
        step = _make_step("routing", prev_hash, rout)
        prev_hash = step.output_hash
        trace.steps.append(step)

        # ── Step 2: rule_engine ────────────────────────────────
        rule_out = {
            "violations_count": len(rule_result.violations) if rule_result else 0,
            "total_score": getattr(rule_result, "total_score", None),
            "violation_ids": sorted(
                [v.rule_id for v in (rule_result.violations if rule_result else []) if v.rule_id]
            ),
        }
        step = _make_step("rule_engine", prev_hash, rule_out)
        prev_hash = step.output_hash
        trace.steps.append(step)

        # ── Step 3: parameter_bias ─────────────────────────────
        bias_out = {
            "findings_count": len(bias_result.findings) if bias_result else 0,
            "risk_score": getattr(bias_result, "risk_score", None),
            "critical_count": getattr(bias_result, "critical_count", 0),
            "high_count": getattr(bias_result, "high_count", 0),
            "pattern_ids": sorted(
                [f.pattern_id for f in (bias_result.findings if bias_result else []) if f.pattern_id]
            ),
        }
        step = _make_step("parameter_bias", prev_hash, bias_out)
        prev_hash = step.output_hash
        trace.steps.append(step)

        # ── Step 4: llm (snapshot — non-deterministic) ─────────
        llm_out: dict = {}
        if llm_result:
            llm_out = {
                "violations_count": len(llm_result.violations),
                "model_used": llm_result.model_used,
                "tokens_used": llm_result.tokens_used,
                "cost_yuan": llm_result.cost_yuan,
                "sections_analyzed": llm_result.sections_analyzed,
                "sections_skipped": llm_result.sections_skipped,
                "error": llm_result.error,
                # ponytail: snapshot full violations for replay, not just counts
                "violation_types": sorted(set(
                    lv.type for lv in llm_result.violations if lv.type
                )),
            }
        step = _make_step("llm", prev_hash, llm_out)
        prev_hash = step.output_hash
        trace.steps.append(step)

        # ── Step 5: decision_input ─────────────────────────────
        di = _canonical_for_step(decision_input.model_dump(mode="json"))
        step = _make_step("decision_input", prev_hash, di)
        prev_hash = step.output_hash
        trace.steps.append(step)

        # ── Step 6: policy_decision ────────────────────────────
        pd = _canonical_for_step(policy_decision.model_dump(mode="json"))
        step = StepSnapshot(
            step="policy_decision",
            input_snapshot=di,
            output_snapshot=pd,
            input_hash=prev_hash,
            output_hash=policy_decision.decision_hash,
        )
        trace.terminal_hash = policy_decision.decision_hash
        trace.steps.append(step)

        return trace

    def verify_chain(self) -> dict:
        """Verify the hash chain integrity end-to-end.

        Returns {"valid": bool, "errors": [...], "checks": {...}}.
        """
        errors: list[str] = []
        checks: dict[str, bool] = {}

        # ── root hash ──
        if self.steps:
            expected_root = sha256_hex(_canonical_json(self.steps[0].input_snapshot))
            checks["root_hash"] = self.root_hash == expected_root
            if not checks["root_hash"]:
                errors.append("root_hash mismatch")

        # ── step chain ──
        for i, step in enumerate(self.steps):
            if i == 0:
                expected_in = sha256_hex(_canonical_json(step.input_snapshot))
                if step.input_hash != expected_in:
                    errors.append(f"step[{i}] ({step.step}) input_hash mismatch")
                    checks[f"step[{i}].input"] = False
                else:
                    checks[f"step[{i}].input"] = True
            else:
                expected_in = self.steps[i - 1].output_hash
                if step.input_hash != expected_in:
                    errors.append(
                        f"step[{i}] ({step.step}) chain broken: "
                        f"expected {expected_in[:16]}..., got {step.input_hash[:16]}..."
                    )
                    checks[f"step[{i}].chain"] = False
                else:
                    checks[f"step[{i}].chain"] = True

            # output_hash (except policy_decision which uses PolicyKernel's hash)
            if step.step != "policy_decision" and step.output_snapshot is not None:
                expected_out = sha256_hex(
                    step.input_hash.encode() + _canonical_json(step.output_snapshot)
                )
                if step.output_hash != expected_out:
                    errors.append(
                        f"step[{i}] ({step.step}) output_hash mismatch"
                    )
                    checks[f"step[{i}].output"] = False
                else:
                    checks[f"step[{i}].output"] = True

        # ── terminal hash ──
        if self.steps:
            checks["terminal_hash"] = self.terminal_hash == self.decision_hash
            if not checks["terminal_hash"]:
                errors.append("terminal_hash != decision_hash")

        # ── count check ──
        checks["step_count"] = len(self.steps) == 7
        if not checks["step_count"]:
            errors.append(f"expected 7 steps, got {len(self.steps)}")

        valid = len(errors) == 0
        return {"valid": valid, "errors": errors, "checks": checks}

    def to_dict(self) -> dict:
        """Serialize to a JSON-serializable dict for storage."""
        return {
            "steps": [s.to_dict() for s in self.steps],
            "root_hash": self.root_hash,
            "terminal_hash": self.terminal_hash,
            "decision_hash": self.decision_hash,
            "schema_version": self.schema_version,
            "file_hash": self.file_hash,
            "file_name": self.file_name,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AuditTrace":
        """Deserialize from stored dict."""
        trace = cls()
        trace.steps = [StepSnapshot.from_dict(s) for s in d.get("steps", [])]
        trace.root_hash = d.get("root_hash", "")
        trace.terminal_hash = d.get("terminal_hash", "")
        trace.decision_hash = d.get("decision_hash", "")
        trace.schema_version = d.get("schema_version", "")
        trace.file_hash = d.get("file_hash", "")
        trace.file_name = d.get("file_name", "")
        return trace


# ═══════════════════════════════════════════════════════════════
# Replay
# ═══════════════════════════════════════════════════════════════

def replay_decision(trace: AuditTrace) -> PolicyDecision:
    """Replay the policy decision from the stored DecisionInput snapshot.

    Given a valid AuditTrace, extracts the DecisionInput from the
    'decision_input' step and re-runs PolicyKernel.decide().

    Returns the replayed PolicyDecision. Its decision_hash must match
    the stored decision_hash for the trace to be valid.

    Raises ValueError if no decision_input step is found.
    """
    for step in trace.steps:
        if step.step == "decision_input" and step.output_snapshot:
            # Parse back into DecisionInput — Pydantic handles version routing
            raw = step.output_snapshot
            # _canonical_for_step may have converted enums to strings;
            # model_validate handles this for known enum fields
            di = DecisionInput.model_validate(raw)
            return policy_kernel.decide(di)

    raise ValueError("No decision_input step found in trace")


def verify_replay(trace: AuditTrace) -> dict:
    """Full replay verification.

    1. Verify the hash chain (verify_chain)
    2. Replay DecisionInput → PolicyDecision
    3. Verify PolicyKernel's internal trace (verify_trace)
    4. Compare replayed decision_hash with stored

    Returns {"valid": bool, "errors": [...], "checks": {...}}.
    """
    errors: list[str] = []
    checks: dict[str, bool] = {}

    # ── 1. Hash chain ──
    chain = trace.verify_chain()
    checks.update(chain.get("checks", {}))
    if not chain["valid"]:
        errors.extend(chain["errors"])

    # ── 2. Replay ──
    try:
        replayed = replay_decision(trace)
    except Exception as e:
        errors.append(f"replay failed: {e}")
        return {"valid": False, "errors": errors, "checks": checks}

    # ── 3. Decision hash match ──
    checks["decision_hash_match"] = replayed.decision_hash == trace.decision_hash
    if not checks["decision_hash_match"]:
        errors.append(
            f"decision_hash mismatch: replayed={replayed.decision_hash[:16]}..., "
            f"stored={trace.decision_hash[:16]}..."
        )

    # ── 4. PolicyKernel internal trace verification ──
    di_step = None
    for s in trace.steps:
        if s.step == "decision_input" and s.output_snapshot:
            di_step = s
            break
    if di_step:
        try:
            di = DecisionInput.model_validate(di_step.output_snapshot)
            vt = verify_trace(di, replayed)
            checks["policy_trace_valid"] = vt.get("valid", False)
            if not vt.get("valid"):
                errors.append(f"policy trace invalid: {vt.get('errors', [])}")
        except Exception as e:
            errors.append(f"policy trace check failed: {e}")
            checks["policy_trace_valid"] = False

    valid = len(errors) == 0
    return {"valid": valid, "errors": errors, "checks": checks}


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _make_step(name: str, prev_hash: str, output: dict) -> StepSnapshot:
    """Build a pipeline step with computed hashes."""
    out_bytes = _canonical_json(output)
    output_hash = sha256_hex(prev_hash.encode() + out_bytes)
    return StepSnapshot(
        step=name,
        input_snapshot=None,  # implicit — it's the previous step's output
        output_snapshot=output,
        input_hash=prev_hash,
        output_hash=output_hash,
    )


def _canonical_for_step(obj: Any) -> Any:
    """Recursively make an object JSON-safe with stable ordering.

    Mirrors _for_json in policy_kernel.py but operates on plain dicts/lists,
    not Pydantic models (which are already serialized via model_dump).
    """
    if isinstance(obj, dict):
        return {k: _canonical_for_step(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, (list, tuple, set)):
        return [_canonical_for_step(item) for item in obj]
    elif isinstance(obj, Enum):
        return obj.value
    elif isinstance(obj, bytes):
        return obj.hex()
    elif obj is None or isinstance(obj, (int, float, str, bool)):
        return obj
    else:
        return str(obj)


# ═══════════════════════════════════════════════════════════════
# Compatibility: wrap existing pipeline results into an AuditTrace
# ═══════════════════════════════════════════════════════════════

def capture_from_check_endpoint(
    *,
    file_hash: str = "",
    file_name: str = "",
    parsed,            # ParsedDocument
    routing_result,    # RoutingResult
    rule_result,       # RuleEngineResult
    bias_result,       # ParameterBiasResult
    llm_result,        # LLMEngineResult | None
    decision_input,    # DecisionInput
    policy_decision,   # PolicyDecision
    industries: list[str] | None = None,
    platform: str | None = None,
    budget: float | None = None,
    procurement_method: str = "",
    project_type: str = "",
) -> AuditTrace:
    """Convenience wrapper matching the check.py endpoint's local variables.

    ponytail: thin wrapper — the real logic is in AuditTrace.from_pipeline().
    """
    return AuditTrace.from_pipeline(
        file_hash=file_hash,
        file_name=file_name,
        parsed_sections=parsed.sections if parsed else {},
        budget=budget,
        procurement_method=procurement_method,
        project_type=project_type,
        industries=industries,
        platform=platform,
        routing_result=routing_result,
        rule_result=rule_result,
        bias_result=bias_result,
        llm_result=llm_result,
        decision_input=decision_input,
        policy_decision=policy_decision,
    )
