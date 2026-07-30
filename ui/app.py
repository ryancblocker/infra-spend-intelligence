"""
Purpose: Streamlit app entry point for the PACT executive control tower interface.
Inputs: Agent output JSON files under outputs/ and optional local CSV datasets for charting.
Outputs: Interactive multi-page dashboard navigation and KPI presentation.
Assigned Team Member: RYAN
Dependencies: streamlit, json, pathlib.
"""

from __future__ import annotations

import streamlit as st


st.set_page_config(page_title="PACT Control Tower", page_icon="PACT", layout="wide")

st.title("PACT - Proactive Agreement & Contract Tracker")
st.caption("Agentic Infrastructure Contract & Spend Intelligence Platform")

st.markdown(
    """
### Control Tower Navigation
Use the left sidebar to access:
- Executive Dashboard
- Savings Opportunities
- Renewal Risks
- Optimization Scenarios
- Agent Results

### TODO (RYAN)
- Add global filters (vendor, service type, region)
- Add date range controls and drill-down links
- Add chart-level export and CSV download actions
"""
)
