"""
Purpose: Compare keep/cancel/renegotiate scenarios including fees and break-even timelines.
Inputs: outputs/scenario_comparison_output.json.
Outputs: Streamlit scenario comparison table and recommendation framing.
Assigned Team Member: RYAN
Dependencies: streamlit, json, pathlib.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st


BASE_DIR = Path(__file__).resolve().parents[2]
SCENARIO_FILE = BASE_DIR / "outputs" / "scenario_comparison_output.json"

st.header("Optimization Scenarios")

if SCENARIO_FILE.exists():
    payload = json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))
    st.json(payload.get("scenarios", []))
else:
    st.warning("scenario_comparison_output.json not found. Run scenario_comparison_agent.py first.")

# TODO(RYAN): Add side-by-side cards and break-even timeline visualization.
