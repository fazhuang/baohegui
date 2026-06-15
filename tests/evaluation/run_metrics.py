#!/usr/bin/env python3
"""Evaluation metrics runner for baohegui compliance check system.

Usage:
    python3 tests/evaluation/run_metrics.py

Runs predefined test cases through the forbidden word matcher and computes:
  - Per-case pass/fail for targeted risk detection
  - Overall precision, recall, F1
  - Missed risks and false positives summary

Note: test cases use minimal text snippets. The evaluation focuses on
forbidden-pattern matching (type="forbidden") since format/keyword/section
checks require full document structure.
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from app.engine.rule_engine import RuleEngine

logging.basicConfig(level=logging.WARNING)

RULES_DIR = str(Path(__file__).resolve().parent.parent.parent / "rules")
TEST_CASES_PATH = str(Path(__file__).resolve().parent / "test_cases.json")


def load_test_cases() -> list[dict]:
    with open(TEST_CASES_PATH, encoding="utf-8") as f:
        return json.load(f)


def run_test(case: dict) -> dict:
    """Run the forbidden-word checker on a single test case."""
    engine = RuleEngine(rules_dir=RULES_DIR)
    sections = case["sections"]
    # Only check forbidden-pattern violations (the targeted risk types)
    engine_result = engine.run(sections=sections)
    detected_forbidden = {
        v.rule_id
        for v in engine_result.violations
        if v.rule_type == "forbidden"
    }

    expected_forbidden = {
        r["rule_id"] for r in case["expected_rules"]
    }

    tp = len(detected_forbidden & expected_forbidden)
    fp = len(detected_forbidden - expected_forbidden)
    fn = len(expected_forbidden - detected_forbidden)

    return {
        "case_id": case["id"],
        "case_name": case["name"],
        "expected_risk_level": case["expected_risk_level"],
        "detected_forbidden": sorted(detected_forbidden),
        "expected_forbidden": sorted(expected_forbidden),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "passed": fn == 0,
    }


def compute_metrics(results: list[dict]) -> dict:
    total_tp = sum(r["tp"] for r in results)
    total_fp = sum(r["fp"] for r in results)
    total_fn = sum(r["fn"] for r in results)

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "total_cases": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        "total_tp": total_tp,
        "total_fp": total_fp,
        "total_fn": total_fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def main():
    cases = load_test_cases()
    results = [run_test(c) for c in cases]

    print("=" * 70)
    print("  包合规 规则引擎评测结果")
    print("  焦点: 禁用词模式匹配 (type=forbidden)")
    print("=" * 70)

    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        details = f"命中: {r['detected_forbidden']}"
        if not r["passed"]:
            details = f"预期: {r['expected_forbidden']}, 命中: {r['detected_forbidden']}"
        print(f"  [{status}]  {r['case_name']}")
        print(f"          {details}")

    print()
    metrics = compute_metrics(results)
    print("-" * 70)
    print(f"  总用例: {metrics['total_cases']}")
    print(f"  通过: {metrics['passed']}, 失败: {metrics['failed']}")
    print(f"  真阳性: {metrics['total_tp']}, 假阳性: {metrics['total_fp']}, 漏检: {metrics['total_fn']}")
    print(f"  精确率: {metrics['precision']}, 召回率: {metrics['recall']}, F1: {metrics['f1']}")
    print("-" * 70)

    sys.exit(0 if metrics["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
