"""
Purpose: Present waste findings and quantified savings opportunities by category.
Inputs: outputs/waste_findings.json and benchmark context from data/benchmark_rates.csv.
Outputs: Streamlit tables/charts for underutilization and potential savings actions.
Assigned Team Member: RYAN
Dependencies: streamlit, json, pathlib.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st


BASE_DIR = Path(__file__).resolve().parents[2]
WASTE_FILE = BASE_DIR / "outputs" / "waste_findings.json"

st.header("Savings Opportunities")

if WASTE_FILE.exists():
    waste = json.loads(WASTE_FILE.read_text(encoding="utf-8"))
    st.metric("Estimated Annual Savings", f"${waste.get('estimated_annual_savings', 0):,.0f}")
    st.json(waste.get("findings", {}))
else:
    st.warning("waste_findings.json not found. Run waste_detection_agent.py first.")

# TODO(RYAN): Replace JSON viewer with categorized dataframes and charts.
