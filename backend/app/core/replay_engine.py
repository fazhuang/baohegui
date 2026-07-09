"""Replay Engine — deterministic end-to-end audit trail for the compliance pipeline.

Pipeline: input → routing → rule_engine → parameter_bias → llm_boundary → decision_input → policy_decision

Each step stores input_snapshot + output_snapshot + hash(prev_hash || canonical(output)).
The LLM step is a snapshot boundary (non-deterministic); all other steps are deterministic.

Key invariant: terminal_hash ≠ decision_hash.
  - decision_hash: PolicyKernel's internal 5-layer hash
  - terminal_hash: outer pipeline chain terminal hash = SHA256(prev || canonical(policy_decision_snapshot))

Replay verifies:
  1. Hash chain integrity (every link recomputed)
  2. Fixed step sequence (name + count)
  3. Metadata consistency (file_hash, schema_version)
  4. Semantic replay of DecisionInput → PolicyDecision via PolicyKernel
  5. PolicyKernel's internal trace verification (verify_trace)
  6. Stored policy_decision snapshot matches replayed decision
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
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

# Fixed step sequence — order and names are invariant
_PIPELINE_STEPS = (
    "input",
    "routing",
    "rule_engine",
    "parameter_bias",
    "llm_boundary",
    "decision_input",
    "policy_decision",
)


# ═══════════════════════════════════════════════════════════════
# Step snapshot
# ═══════════════════════════════════════════════════════════════

@dataclass
class StepSnapshot:
    """One step in the pipeline trace with hash chain links."""
    step: str                             # must be one of _PIPELINE_STEPS
    input_snapshot: dict | None = None    # canonical input (None for implicit chain links)
    output_snapshot: dict | None = None   # canonical output
    input_hash: str = ""                  # SHA-256(input_snapshot) or prev.output_hash
    output_hash: str = ""                 # SHA-256(input_hash || canonical(output_snapshot))

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
        return cls(**{k: d.get(k) for k in ("step", "input_snapshot", "output_snapshot",
                                              "input_hash", "output_hash")})


# ═══════════════════════════════════════════════════════════════
# AuditTrace
# ═══════════════════════════════════════════════════════════════

class AuditTrace:
    """Full pipeline audit trace with hash chain."""

    steps: list[StepSnapshot]
    root_hash: str       # SHA-256(canonical(input_step.input_snapshot))
    terminal_hash: str   # SHA-256(prev || canonical(policy_decision_snapshot))
    decision_hash: str   # PolicyKernel.decision_hash (embedded in policy_decision snapshot)
    schema_version: str  # e.g. "2.1.0"
    file_hash: str       # SHA-256 of uploaded file bytes
    file_name: str

    def __init__(self):
        self.steps = []
        self.root_hash = ""
        self.terminal_hash = ""
        self.decision_hash = ""
        self.schema_version = ""
        self.file_hash = ""
        self.file_name = ""

    # ── Construction ───────────────────────────────────────────

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
        llm_boundary: LLMBoundary | None = None,
        decision_input: DecisionInput | None = None,
        policy_decision: PolicyDecision | None = None,
    ) -> "AuditTrace":
        """Build trace from post-pipeline snapshots."""
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

        # ── Step 0: input ────────────────────────────────────
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
        step = StepSnapshot(
            step="input", input_snapshot=inp, output_snapshot=inp,
            input_hash=h,
            output_hash=sha256_hex(h.encode() + _canonical_json(inp)),
        )
        trace.root_hash = h
        prev_hash = step.output_hash
        trace.steps.append(step)

        # ── Step 1: routing ──────────────────────────────────
        rout = _canonical_for_step(routing_result.model_dump(mode="json")) if routing_result else {}
        step = _make_step("routing", prev_hash, rout)
        prev_hash = step.output_hash
        trace.steps.append(step)

        # ── Step 2: rule_engine ──────────────────────────────
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

        # ── Step 3: parameter_bias ───────────────────────────
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

        # ── Step 4: llm_boundary — snapshot only ─────────────
        llm_out = llm_boundary.to_dict() if llm_boundary else {}
        step = _make_step("llm_boundary", prev_hash, llm_out)
        prev_hash = step.output_hash
        trace.steps.append(step)

        # ── Step 5: decision_input ───────────────────────────
        di = _canonical_for_step(decision_input.model_dump(mode="json"))
        step = _make_step("decision_input", prev_hash, di)
        prev_hash = step.output_hash
        trace.steps.append(step)

        # ── Step 6: policy_decision ──────────────────────────
        pd = _canonical_for_step(policy_decision.model_dump(mode="json"))
        terminal = sha256_hex(prev_hash.encode() + _canonical_json(pd))
        step = StepSnapshot(
            step="policy_decision",
            input_snapshot=di,
            output_snapshot=pd,
            input_hash=prev_hash,
            output_hash=terminal,
        )
        trace.terminal_hash = terminal
        trace.steps.append(step)

        return trace

    # ── Verification ──────────────────────────────────────────

    _EXPECTED_STEPS = _PIPELINE_STEPS
    _EXPECTED_COUNT = len(_PIPELINE_STEPS)

    def verify_chain(self) -> dict:
        """Full integrity verification.

        Checks:
        1. Fixed step sequence (name + count) — no missing, extra, renamed, or reordered
        2. Root hash recomputation
        3. Chain continuity: each input_hash == previous.output_hash
        4. Each output_hash recomputation
        5. Terminal hash == last step output_hash
        6. Metadata: file_hash, schema_version match corresponding snapshots
        7. PolicyDecision snapshot's decision_hash == top-level decision_hash
        8. No downgrade: policy_decision snapshot output_hash matches terminal_hash
        """
        errors: list[str] = []
        checks: dict[str, bool] = {}

        # ── 0. Step sequence ──
        actual_steps = tuple(s.step for s in self.steps)
        checks["step_count"] = len(self.steps) == self._EXPECTED_COUNT
        if not checks["step_count"]:
            errors.append(
                f"step count: expected {self._EXPECTED_COUNT}, got {len(self.steps)}"
            )
        checks["step_sequence"] = actual_steps == self._EXPECTED_STEPS
        if not checks["step_sequence"]:
            errors.append(
                f"step sequence: expected {self._EXPECTED_STEPS}, got {actual_steps}"
            )

        if not self.steps:
            return {"valid": False, "errors": errors, "checks": checks}

        # ── 1. Root hash ──
        root_snapshot = self.steps[0].input_snapshot
        if root_snapshot is not None:
            expected_root = sha256_hex(_canonical_json(root_snapshot))
            checks["root_hash"] = self.root_hash == expected_root
            if not checks["root_hash"]:
                errors.append("root_hash mismatch")
        else:
            checks["root_hash"] = False
            errors.append("missing input step snapshot")

        # ── 2. Metadata consistency ──
        inp = self.steps[0].output_snapshot or {}
        checks["file_hash_consistent"] = self.file_hash == inp.get("file_hash", "")
        if not checks["file_hash_consistent"]:
            errors.append(
                f"file_hash mismatch: top={self.file_hash!r}, snapshot={inp.get('file_hash', '')!r}"
            )

        # schema_version from policy_decision step
        pd_step = None
        for s in self.steps:
            if s.step == "policy_decision":
                pd_step = s
                break
        if pd_step and pd_step.output_snapshot:
            pd_sv = pd_step.output_snapshot.get("schema_version", "")
            checks["schema_version_consistent"] = self.schema_version == pd_sv
            if not checks["schema_version_consistent"]:
                errors.append(
                    f"schema_version mismatch: top={self.schema_version!r}, pd_snapshot={pd_sv!r}"
                )

            # decision_hash within policy_decision snapshot
            pd_dh = pd_step.output_snapshot.get("decision_hash", "")
            checks["decision_hash_in_snapshot"] = self.decision_hash == pd_dh
            if not checks["decision_hash_in_snapshot"]:
                errors.append(
                    f"decision_hash: top={self.decision_hash[:16]}..., pd_snapshot={pd_dh[:16] if pd_dh else 'MISSING'}..."
                )

        # ── 3. Chain integrity step-by-step ──
        for i, step in enumerate(self.steps):
            prefix = f"step[{i}]({step.step})"

            if i == 0:
                # Step 0: input_hash = SHA256(canonical(input_snapshot))
                if step.input_snapshot is not None:
                    expected_in = sha256_hex(_canonical_json(step.input_snapshot))
                    if step.input_hash != expected_in:
                        errors.append(f"{prefix} input_hash mismatch")
                        checks[f"{prefix}.input"] = False
                    else:
                        checks[f"{prefix}.input"] = True
                else:
                    errors.append(f"{prefix} missing input_snapshot")
                    checks[f"{prefix}.input"] = False
            else:
                expected_in = self.steps[i - 1].output_hash
                if step.input_hash != expected_in:
                    errors.append(
                        f"{prefix} chain broken: expected {expected_in[:16]}..., "
                        f"got {step.input_hash[:16]}..."
                    )
                    checks[f"{prefix}.chain"] = False
                else:
                    checks[f"{prefix}.chain"] = True

            # output_hash recomputation for ALL steps
            if step.output_snapshot is not None:
                expected_out = sha256_hex(
                    step.input_hash.encode() + _canonical_json(step.output_snapshot)
                )
                if step.output_hash != expected_out:
                    errors.append(f"{prefix} output_hash mismatch")
                    checks[f"{prefix}.output"] = False
                else:
                    checks[f"{prefix}.output"] = True
            else:
                errors.append(f"{prefix} missing output_snapshot")
                checks[f"{prefix}.output"] = False

        # ── 4. Terminal hash ──
        last = self.steps[-1]
        checks["terminal_hash"] = self.terminal_hash == last.output_hash
        if not checks["terminal_hash"]:
            errors.append(
                f"terminal_hash mismatch: stored={self.terminal_hash[:16]}..., "
                f"last_output={last.output_hash[:16]}..."
            )

        valid = len(errors) == 0
        return {"valid": valid, "errors": errors, "checks": checks}

    # ── Serialization ─────────────────────────────────────────

    def to_dict(self) -> dict:
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
# LLM Boundary — snapshot of non-deterministic external call
# ═══════════════════════════════════════════════════════════════

@dataclass
class LLMBoundary:
    """Snapshot of the LLM call — a non-deterministic external boundary.

    Replay must NOT call the model again. It must use the stored
    normalized_output and verify it matches the DecisionInput's LLM inputs.
    """
    provider: str = ""
    model: str = ""
    model_version: str = ""        # from API metadata if available
    prompt_hash: str = ""          # SHA-256 of the assembled prompt text
    temperature: float = 0.0
    seed: int | None = None
    max_tokens: int = 0
    raw_response_hash: str = ""    # SHA-256 of raw API response bytes
    normalized_violations: list[dict] = None  # list of LLMViolation as dicts
    tokens_used: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    cost_yuan: float = 0.0
    model_used: str = ""           # actual model name returned by API
    sections_analyzed: int = 0
    sections_skipped: int = 0
    error: str | None = None
    # Asset version fingerprints
    rule_asset_hash: str = ""      # SHA-256 of loaded rules content
    prompt_asset_hash: str = ""    # SHA-256 of prompt template content

    def __post_init__(self):
        if self.normalized_violations is None:
            self.normalized_violations = []

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "model_version": self.model_version,
            "prompt_hash": self.prompt_hash,
            "temperature": self.temperature,
            "seed": self.seed,
            "max_tokens": self.max_tokens,
            "raw_response_hash": self.raw_response_hash,
            "normalized_violations": self.normalized_violations,
            "tokens_used": self.tokens_used,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "cost_yuan": self.cost_yuan,
            "model_used": self.model_used,
            "sections_analyzed": self.sections_analyzed,
            "sections_skipped": self.sections_skipped,
            "error": self.error,
            "rule_asset_hash": self.rule_asset_hash,
            "prompt_asset_hash": self.prompt_asset_hash,
        }

    @classmethod
    def from_llm_result(cls, llm_result, *, prompt_text: str = "",
                        raw_response_text: str = "",
                        rule_asset_hash: str = "",
                        prompt_asset_hash: str = "",
                        provider: str = "", model: str = "",
                        temperature: float = 0.0, seed: int | None = None,
                        max_tokens: int = 0) -> "LLMBoundary":
        """Capture LLM result into a boundary snapshot."""
        import hashlib
        return cls(
            provider=provider,
            model=model,
            model_version=getattr(llm_result, "model_used", ""),
            prompt_hash=hashlib.sha256(prompt_text.encode()).hexdigest() if prompt_text else "",
            temperature=temperature,
            seed=seed,
            max_tokens=max_tokens,
            raw_response_hash=hashlib.sha256(raw_response_text.encode()).hexdigest() if raw_response_text else "",
            normalized_violations=[
                lv.model_dump(mode="json") if hasattr(lv, "model_dump") else lv
                for lv in (llm_result.violations if llm_result else [])
            ],
            tokens_used=getattr(llm_result, "tokens_used", 0),
            tokens_input=getattr(llm_result, "tokens_input", 0),
            tokens_output=getattr(llm_result, "tokens_output", 0),
            cost_yuan=getattr(llm_result, "cost_yuan", 0.0),
            model_used=getattr(llm_result, "model_used", ""),
            sections_analyzed=getattr(llm_result, "sections_analyzed", 0),
            sections_skipped=getattr(llm_result, "sections_skipped", 0),
            error=getattr(llm_result, "error", None),
            rule_asset_hash=rule_asset_hash,
            prompt_asset_hash=prompt_asset_hash,
        )


# ═══════════════════════════════════════════════════════════════
# OCR Boundary — snapshot of document extraction
# ═══════════════════════════════════════════════════════════════

@dataclass
class OCRBoundary:
    """Snapshot of document parsing/extraction — a deterministic boundary.

    OCR is not yet implemented. When it is, treat it like LLM: snapshot
    the extraction mode + output hashes, fail closed if OCR is needed but
    unavailable.
    """
    extraction_mode: str = "text_layer"   # text_layer | ocr | mixed
    parser_version: str = ""              # version tag
    input_file_hash: str = ""             # SHA-256 of uploaded file bytes
    sections_hash: str = ""               # SHA-256 of canonical sections dict
    full_text_hash: str = ""              # SHA-256 of full_text
    page_count: int = 0
    parse_quality: str = "ok"             # ok | text_layer | ocr | partial | failed
    parse_quality_detail: str = ""
    is_scanned: bool = False              # True if input is a scanned image
    ocr_available: bool = False           # True when OCR backend is configured
    ocr_model: str = ""                   # OCR model name/version when available

    def to_dict(self) -> dict:
        return {
            "extraction_mode": self.extraction_mode,
            "parser_version": self.parser_version,
            "input_file_hash": self.input_file_hash,
            "sections_hash": self.sections_hash,
            "full_text_hash": self.full_text_hash,
            "page_count": self.page_count,
            "parse_quality": self.parse_quality,
            "parse_quality_detail": self.parse_quality_detail,
            "is_scanned": self.is_scanned,
            "ocr_available": self.ocr_available,
            "ocr_model": self.ocr_model,
        }

    @classmethod
    def from_parsed(cls, parsed, *, file_hash: str = "") -> "OCRBoundary":
        """Capture parser output into a boundary snapshot."""
        import hashlib
        sections = parsed.sections if parsed else {}
        full_text = parsed.full_text if parsed else ""
        sections_canonical = _canonical_json(_canonical_for_step(
            {k: v for k, v in sorted(sections.items())}
        ))
        return cls(
            extraction_mode="text_layer" if getattr(parsed, "parse_quality", "ok") != "ocr" else "ocr",
            parser_version="v3",
            input_file_hash=file_hash,
            sections_hash=hashlib.sha256(sections_canonical).hexdigest(),
            full_text_hash=hashlib.sha256(full_text.encode()).hexdigest() if full_text else "",
            page_count=getattr(parsed, "page_count", 0) or 0,
            parse_quality=getattr(parsed, "parse_quality", "ok") or "ok",
            parse_quality_detail=getattr(parsed, "parse_quality_detail", "") or "",
            is_scanned=getattr(parsed, "parse_quality", "ok") == "ocr",
            ocr_available=False,
            ocr_model="",
        )


# ═══════════════════════════════════════════════════════════════
# Replay
# ═══════════════════════════════════════════════════════════════

def replay_decision(trace: AuditTrace) -> PolicyDecision:
    """Replay the policy decision from the stored DecisionInput snapshot.

    Does NOT call LLM or any external service. Extracts DecisionInput from
    the 'decision_input' step and re-runs PolicyKernel.decide() (deterministic).

    Returns the replayed PolicyDecision.
    """
    for step in trace.steps:
        if step.step == "decision_input" and step.output_snapshot:
            raw = step.output_snapshot
            di = DecisionInput.model_validate(raw)
            return policy_kernel.decide(di)

    raise ValueError("No decision_input step found in trace")


def verify_replay(trace: AuditTrace) -> dict:
    """Full replay verification.

    1. Hash chain integrity (verify_chain)
    2. Semantic replay: DecisionInput → PolicyDecision via PolicyKernel
    3. Compare replayed decision_hash with stored decision_hash
    4. Verify replayed PolicyKernel internal trace (verify_trace)
    5. Compare replayed policy_decision snapshot with stored snapshot
    6. Verify LLM normalized output in DecisionInput matches stored LLM boundary

    Returns {"valid": bool, "errors": [...], "checks": {...}}.
    """
    errors: list[str] = []
    checks: dict[str, bool] = {}

    # ── 1. Hash chain ──
    chain = trace.verify_chain()
    checks.update({f"chain.{k}": v for k, v in chain.get("checks", {}).items()})
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
            f"decision_hash: replayed={replayed.decision_hash[:16]}..., "
            f"stored={trace.decision_hash[:16]}..."
        )

    # ── 4. PolicyKernel internal trace ──
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
                errors.append(f"policy trace: {vt.get('errors', [])}")
        except Exception as e:
            errors.append(f"policy trace check: {e}")
            checks["policy_trace_valid"] = False

    # ── 5. Stored snapshot vs replayed ──
    pd_step = None
    for s in trace.steps:
        if s.step == "policy_decision" and s.output_snapshot:
            pd_step = s
            break
    if pd_step:
        replayed_dict = _canonical_for_step(replayed.model_dump(mode="json"))
        stored_dict = _canonical_for_step(pd_step.output_snapshot)
        checks["snapshot_match"] = replayed_dict == stored_dict
        if not checks["snapshot_match"]:
            # Detail which fields differ
            diffs = []
            for k in set(list(replayed_dict.keys()) + list(stored_dict.keys())):
                if replayed_dict.get(k) != stored_dict.get(k):
                    diffs.append(k)
            errors.append(f"policy_decision snapshot differs in: {diffs}")

    # ── 6. LLM boundary consistency ──
    llm_step = None
    for s in trace.steps:
        if s.step == "llm_boundary" and s.output_snapshot:
            llm_step = s
            break
    if di_step and llm_step:
        stored_llm = llm_step.output_snapshot
        di_llm_violations = di_step.output_snapshot.get("llm_violations", [])
        stored_norm = stored_llm.get("normalized_violations", [])
        # Compare type + risk_level counts (schema-preserving comparison)
        di_types = sorted((v.get("type", ""), v.get("risk_level", ""))
                          for v in di_llm_violations)
        stored_types = sorted((v.get("type", ""), v.get("risk_level", ""))
                              for v in stored_norm)
        checks["llm_boundary_consistent"] = di_types == stored_types
        if not checks["llm_boundary_consistent"]:
            errors.append("LLM normalized violations in DecisionInput differ from stored LLM boundary")

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
        input_snapshot=None,
        output_snapshot=output,
        input_hash=prev_hash,
        output_hash=output_hash,
    )


def _canonical_for_step(obj: Any) -> Any:
    """Recursively make an object JSON-safe with stable ordering.

    Mirrors _for_json in policy_kernel.py. Sets are always sorted.
    Lists whose keys are in _SORTABLE_LIST_KEYS are also sorted
    (these fields originate from Pydantic set types that model_dump
    converts to lists with non-deterministic iteration order).
    """
    if isinstance(obj, dict):
        result = {}
        for k, v in sorted(obj.items()):
            val = _canonical_for_step(v)
            if k in _SORTABLE_LIST_KEYS and isinstance(val, list):
                val = sorted(val)
            result[k] = val
        return result
    elif isinstance(obj, set):
        return sorted(_canonical_for_step(item) for item in obj)
    elif isinstance(obj, (list, tuple)):
        return [_canonical_for_step(item) for item in obj]
    elif isinstance(obj, Enum):
        return obj.value
    elif isinstance(obj, bytes):
        return obj.hex()
    elif obj is None or isinstance(obj, (int, float, str, bool)):
        return obj
    else:
        return str(obj)


# Fields that originate from Pydantic set[str] types — model_dump(mode="json")
# converts them to lists with PYTHONHASHSEED-dependent order.
_SORTABLE_LIST_KEYS = frozenset({
    "present_sections", "auto_fail_rule_types", "suppressed_rule_ids",
    "required_sections", "industries", "pattern_ids", "violation_ids",
    "violation_types", "section_names", "overrides_applied",
    "missing", "llm_task_list", "platform_codes",
})
