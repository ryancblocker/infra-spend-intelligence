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

import pandas as pd
import streamlit as st


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "outputs"

st.markdown(
    """
<style>
.main { background: linear-gradient(180deg, #f4f8ff 0%, #ffffff 34%); }
.hero-mini {
    padding: 0.95rem 1.1rem;
    border-radius: 14px;
    background: radial-gradient(circle at 6% 8%, #74c0fc 0%, transparent 28%),
                            radial-gradient(circle at 95% 12%, #d0bfff 0%, transparent 26%),
                            linear-gradient(130deg, #124e78 0%, #5a67d8 72%);
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
<div class="hero-mini"><strong>Executive Dashboard</strong><br/>Board-level spend, risk, and savings snapshot.</div>
""",
    unsafe_allow_html=True,
)


def read_json(name: str) -> dict:
    path = OUTPUT_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


summary = read_json("discovery_output.json")
optimization = read_json("financial_optimization_output.json")
renewals = read_json("renewal_intelligence_output.json")
waste = read_json("waste_findings.json")

annual_spend = summary.get("total_annual_spend") if isinstance(summary, dict) else None
savings = optimization.get("total_identified_annual_savings") if isinstance(optimization, dict) else None
if not savings and isinstance(waste, dict):
    savings = waste.get("total_potential_annual_savings")

renewal_summary = renewals.get("summary", {}) if isinstance(renewals, dict) else {}
high_risk = renewal_summary.get("high_risk_contracts")
renewing_90 = renewal_summary.get("contracts_renewing_within_90_days")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Annual Spend", f"${float(annual_spend):,.0f}" if annual_spend else "N/A")
col2.metric("Potential Annual Savings", f"${float(savings):,.0f}" if savings else "N/A")
col3.metric("High-Risk Contracts", f"{int(high_risk)}" if high_risk is not None else "N/A")
col4.metric("Renewals Within 90 Days", f"{int(renewing_90)}" if renewing_90 is not None else "N/A")

st.markdown("### Top Recommendations")
recs = optimization.get("top_recommendations") or optimization.get("recommendations") if isinstance(optimization, dict) else []
if recs:
    rec_df = pd.DataFrame(recs)
    cols = ["recommended_action", "estimated_annual_savings", "risk_level", "confidence"]
    for col in cols:
        if col not in rec_df.columns:
            rec_df[col] = "N/A"
    st.data_editor(
        rec_df[cols].head(6),
        width="stretch",
        hide_index=True,
        disabled=True,
        column_config={
            "recommended_action": "Recommended Action",
            "estimated_annual_savings": st.column_config.NumberColumn("Annual Savings", format="$%d"),
            "risk_level": "Risk",
            "confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
        },
    )
else:
    st.info("No recommendation data available yet.")
