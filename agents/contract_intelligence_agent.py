"""
Purpose: Extract high-value contractual clauses from unstructured contract text files.
Inputs: Text contracts under contract_texts/.
Outputs: JSON file outputs/contract_intelligence_output.json containing parsed clauses and flags.
Assigned Team Member: JESSIE
Dependencies: pathlib, json, re.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
TEXT_DIR = BASE_DIR / "contract_texts"
OUTPUT_FILE = BASE_DIR / "outputs" / "contract_intelligence_output.json"


def extract_flags(text: str) -> dict:
    """Very simple regex-based clause extraction placeholder."""
    return {
        "auto_renew_clause": bool(re.search(r"auto[- ]?renew", text, re.IGNORECASE)),
        "notice_days": re.findall(r"(\d+)\s+days", text, re.IGNORECASE),
        "termination_fee_reference": bool(re.search(r"termination fee", text, re.IGNORECASE)),
        "escalation_reference": bool(re.search(r"escalat|increase", text, re.IGNORECASE)),
    }


def analyze_contracts() -> dict:
    results = []
    for path in sorted(TEXT_DIR.glob("contract_*.txt")):
        text = path.read_text(encoding="utf-8")
        # TODO(JESSIE): Replace regex heuristics with robust NLP extraction logic.
        results.append({"contract_file": path.name, "flags": extract_flags(text)})
    return {"contracts": results}


def main() -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = analyze_contracts()
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Contract intelligence output written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
