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

import pandas as pd
import streamlit as st


BASE_DIR = Path(__file__).resolve().parents[2]
WASTE_FILE = BASE_DIR / "outputs" / "waste_findings.json"

st.markdown(
    """
<style>
.main { background: linear-gradient(180deg, #f4f8ff 0%, #ffffff 34%); }
.hero-mini {
    padding: 0.95rem 1.1rem;
    border-radius: 14px;
    background: radial-gradient(circle at 6% 8%, #99e9f2 0%, transparent 26%),
                            radial-gradient(circle at 95% 12%, #d0bfff 0%, transparent 26%),
                            linear-gradient(130deg, #155e75 0%, #4c6ef5 70%);
    color: #fff;
    margin-bottom: 0.9rem;
}
div[data-testid="stDataFrame"],
div[data-testid="stDataEditor"] {
    border: 1px solid #dbe7ff;
    border-radius: 14px;
    overflow: hidden;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNav"] ul {
    gap: 0.35rem;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {
    border-radius: 10px;
    margin: 0.1rem 0;
    border: 1px solid #d6e3ff;
    background: linear-gradient(120deg, #edf4ff 0%, #e9ecff 100%);
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a span {
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 700;
    color: #23436a;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {
    border-color: #9ab6ff;
    background: linear-gradient(120deg, #dbe9ff 0%, #dfe2ff 100%);
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {
    border-color: #637cff;
    background: linear-gradient(120deg, #2a6f97 0%, #5a67d8 100%);
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] span {
    color: #ffffff;
}
</style>
<div class="hero-mini"><strong>Savings Opportunities</strong><br/>Where the biggest recoverable spend is hiding.</div>
""",
    unsafe_allow_html=True,
)

if WASTE_FILE.exists():
    waste = json.loads(WASTE_FILE.read_text(encoding="utf-8"))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Potential Annual Savings", f"${float(waste.get('total_potential_annual_savings', 0)):,.0f}")
    m2.metric("Potential Monthly Savings", f"${float(waste.get('total_potential_monthly_savings', 0)):,.0f}")
    m3.metric("Total Findings", f"{int(waste.get('number_of_findings', 0))}")
    m4.metric("High Priority", f"{int(waste.get('high_priority_findings', 0))}")

    findings = waste.get("findings", [])
    if findings:
        df = pd.DataFrame(findings)
        cols = [
            "finding_id",
            "category",
            "asset_id",
            "issue",
            "estimated_annual_savings",
            "recommended_action",
            "priority",
        ]
        for col in cols:
            if col not in df.columns:
                df[col] = "N/A"
        st.data_editor(
            df[cols].sort_values(by="estimated_annual_savings", ascending=False),
            width="stretch",
            hide_index=True,
            disabled=True,
            column_config={
                "finding_id": "Finding",
                "category": "Category",
                "asset_id": "Asset",
                "issue": "Issue",
                "estimated_annual_savings": st.column_config.NumberColumn("Annual Savings", format="$%d"),
                "recommended_action": "Recommended Action",
                "priority": "Priority",
            },
        )
    else:
        st.info("No findings available yet.")
else:
    st.warning("waste_findings.json not found. Run waste_detection_agent.py first.")
