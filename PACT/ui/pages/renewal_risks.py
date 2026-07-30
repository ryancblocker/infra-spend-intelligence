"""
Purpose: Visualize renewal deadlines, auto-renew risks, and required review actions.
Inputs: outputs/renewal_intelligence_output.json.
Outputs: Streamlit risk table and deadline-oriented alerts.
Assigned Team Member: RYAN
Dependencies: streamlit, json, pathlib.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st


BASE_DIR = Path(__file__).resolve().parents[2]
RENEWAL_FILE = BASE_DIR / "outputs" / "renewal_intelligence_output.json"

st.header("Renewal Risks")

if RENEWAL_FILE.exists():
    payload = json.loads(RENEWAL_FILE.read_text(encoding="utf-8"))
    st.caption(f"Reference Date: {payload.get('reference_date', 'N/A')}")
    st.json(payload.get("upcoming_renewals", []))
else:
    st.warning("renewal_intelligence_output.json not found. Run renewal_intelligence_agent.py first.")

# TODO(RYAN): Add deadline heatmap and priority scoring.
