"""
Purpose: Provide a consolidated viewer for all agent output artifacts.
Inputs: JSON files in outputs/.
Outputs: Streamlit expandable sections for each agent payload.
Assigned Team Member: RYAN
Dependencies: streamlit, json, pathlib.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "outputs"
FILES = [
    "discovery_output.json",
    "waste_findings.json",
    "contract_intelligence_output.json",
    "renewal_intelligence_output.json",
    "financial_optimization_output.json",
    "scenario_comparison_output.json",
]

st.header("Agent Results")

for name in FILES:
    path = OUTPUT_DIR / name
    with st.expander(name, expanded=False):
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            st.json(payload)
        else:
            st.warning(f"Missing file: {name}")

# TODO(RYAN): Add schema validation and status indicator per output artifact.
