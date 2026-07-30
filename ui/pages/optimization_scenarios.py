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

import pandas as pd
import streamlit as st


BASE_DIR = Path(__file__).resolve().parents[2]
SCENARIO_FILE = BASE_DIR / "outputs" / "scenario_comparison_output.json"

st.markdown(
    """
<style>
.main { background: linear-gradient(180deg, #f4f8ff 0%, #ffffff 34%); }
.hero-mini {
    padding: 0.95rem 1.1rem;
    border-radius: 14px;
    background: radial-gradient(circle at 6% 8%, #74c0fc 0%, transparent 26%),
                            radial-gradient(circle at 95% 12%, #d0bfff 0%, transparent 26%),
                            linear-gradient(130deg, #2c5282 0%, #5a67d8 70%);
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
<div class="hero-mini"><strong>Optimization Scenarios</strong><br/>Keep vs cancel vs renegotiate decision modeling.</div>
""",
    unsafe_allow_html=True,
)

if SCENARIO_FILE.exists():
    payload = json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))
    scenarios = payload.get("scenario_results", [])
    if scenarios:
        df = pd.DataFrame(scenarios)
        if "contract_id" not in df.columns:
            df["contract_id"] = df.get("contract", "N/A")
        if "rationale" not in df.columns:
            df["rationale"] = df.get("issue", "N/A")
        if "vendor" not in df.columns:
            df["vendor"] = "N/A"

        cols = [
            "contract_id",
            "vendor",
            "keep_cost",
            "cancel_cost",
            "renegotiate_cost",
            "projected_savings",
            "recommendation",
            "rationale",
        ]
        for col in cols:
            if col not in df.columns:
                df[col] = "N/A"

        st.data_editor(
            df[cols],
            width="stretch",
            hide_index=True,
            disabled=True,
            column_config={
                "contract_id": "Contract",
                "vendor": "Vendor",
                "keep_cost": st.column_config.NumberColumn("Keep Cost", format="$%d"),
                "cancel_cost": st.column_config.NumberColumn("Cancel Cost", format="$%d"),
                "renegotiate_cost": st.column_config.NumberColumn("Renegotiate Cost", format="$%d"),
                "projected_savings": st.column_config.NumberColumn("Projected Savings", format="$%d"),
                "recommendation": "Recommendation",
                "rationale": "Rationale",
            },
        )
    else:
        st.info("Scenario output is available but currently empty.")
else:
    st.warning("scenario_comparison_output.json not found. Run scenario_comparison_agent.py first.")
