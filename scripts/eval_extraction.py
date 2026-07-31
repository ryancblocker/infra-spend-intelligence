#!/usr/bin/env python
"""
Score the extraction agent against hand-labeled ground truth.

This answers the standing question for the LLM area: is the real model path a
genuine improvement over the deterministic offline fallback, or just slower?
Run it in both modes and compare - and report whatever it says, including a
result where the regex baseline wins. That is a finding, not a failure.

    python scripts/eval_extraction.py --mode offline
    python scripts/eval_extraction.py --mode ollama

The cache is always bypassed so a run measures the extractor, not the cache.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

GROUND_TRUTH_PATH = BASE_DIR / "tests" / "fixtures" / "extraction_ground_truth.json"


def score_field(expected, actual, mode: str) -> bool:
    if mode == "contains":
        if actual is None:
            return False
        return str(expected).lower() in str(actual).lower()
    if isinstance(expected, bool):
        return bool(actual) is expected
    if isinstance(expected, float):
        try:
            return actual is not None and abs(float(actual) - expected) < 1e-6
        except (TypeError, ValueError):
            return False
    if isinstance(expected, int):
        try:
            return actual is not None and int(actual) == expected
        except (TypeError, ValueError):
            return False
    return str(actual or "").strip() == str(expected).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline", "ollama", "anthropic"], required=True)
    args = parser.parse_args()

    os.environ["PACT_LLM_MODE"] = args.mode
    os.environ["PACT_EXTRACTION_CACHE"] = "0"  # measure the extractor, not the cache

    from app import config
    from app.agents import extraction
    from app.tools import vector_store

    config.ensure_runtime_dirs()
    try:
        vector_store.build_index()
    except Exception as exc:  # index is optional for the offline regex path
        print(f"warning: vector index build failed ({exc}); retrieval will return nothing")

    payload = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    match_modes = payload["_match_modes"]
    truth = payload["contracts"]

    per_field: dict[str, list[int]] = {field: [0, 0] for field in match_modes}
    iterations_seen: list[int] = []
    started = time.perf_counter()

    for contract_id, expected_fields in sorted(truth.items()):
        doc = config.CONTRACT_DOCS_DIR / f"{contract_id}.txt"
        if not doc.exists():
            print(f"warning: {doc} missing, skipping")
            continue
        record = extraction.extract_one(contract_id, doc.read_text(encoding="utf-8"))
        iterations_seen.append(record.extraction_iterations)
        for field, expected in expected_fields.items():
            correct = score_field(expected, getattr(record, field, None), match_modes[field])
            per_field[field][0] += int(correct)
            per_field[field][1] += 1

    elapsed = time.perf_counter() - started

    lines = [
        f"# Extraction accuracy - `{args.mode}` mode",
        "",
        f"Contracts scored: {len(iterations_seen)} | "
        f"wall clock: {elapsed:.1f}s | "
        f"mean loop iterations: {sum(iterations_seen) / max(len(iterations_seen), 1):.2f}",
        "",
        "| Field | Correct | Total | Accuracy |",
        "|---|---|---|---|",
    ]
    total_correct = total_scored = 0
    for field, (correct, scored) in per_field.items():
        total_correct += correct
        total_scored += scored
        pct = (correct / scored * 100) if scored else 0.0
        lines.append(f"| `{field}` | {correct} | {scored} | {pct:.0f}% |")

    overall = (total_correct / total_scored * 100) if total_scored else 0.0
    lines += ["| **overall** | "
              f"**{total_correct}** | **{total_scored}** | **{overall:.0f}%** |", ""]

    report = "\n".join(lines)
    print(report)
    out = config.RUNTIME_DIR / f"eval_extraction_{args.mode}.md"
    out.write_text(report + "\n", encoding="utf-8")
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
