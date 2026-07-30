"""
Purpose: Display top-level spend, risk, and savings KPIs for executive stakeholders.
Inputs: outputs/discovery_output.json, outputs/financial_optimization_output.json, outputs/renewal_intelligence_output.json.
Outputs: Streamlit KPI cards, summary charts, and high-level recommendations.
Assigned Team Member: RYAN
Dependencies: streamlit, json, pathlib.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "outputs"


def read_json(name: str) -> dict:
    path = OUTPUT_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


st.header("Executive Dashboard")

summary = read_json("discovery_output.json")
optimization = read_json("financial_optimization_output.json")
renewals = read_json("renewal_intelligence_output.json")

col1, col2, col3 = st.columns(3)
col1.metric("Total Annual Spend", f"${summary.get('summary', {}).get('annual_spend', 0):,.0f}")
col2.metric("Projected Savings", f"${optimization.get('projected_annual_savings', 0):,.0f}")
col3.metric("Upcoming Renewals", len(renewals.get("upcoming_renewals", [])))

# TODO(RYAN): Add trend chart and vendor concentration donut.
st.info("Executive KPI placeholders are active. Expand with richer visuals.")
