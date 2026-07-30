<!--
Purpose: Project-level overview, setup, and operating guide for the PACT platform.
Inputs: Repository source files, synthetic datasets under data/, and agent output artifacts under outputs/.
Outputs: Human-readable guidance for setup, execution order, team ownership, and expected deliverables.
Assigned Team Member: SOFIA
Dependencies: Python 3.10+, streamlit, pandas, plotly (optional), and local file system access.
-->

# PACT - Proactive Agreement & Contract Tracker

PACT is an agentic Infrastructure Contract & Spend Intelligence Platform.

## Executive Control Tower Goals
- View total spend
- View upcoming renewals
- Identify underutilized services
- Compare keep vs cancel vs renegotiate scenarios
- View AI-generated recommendations
- View projected savings opportunities

## Project Workflow
1. Discovery Agent -> outputs/discovery_output.json
2. Waste Detection Agent -> outputs/waste_findings.json
3. Contract Intelligence Agent -> outputs/contract_intelligence_output.json
4. Renewal Intelligence Agent -> outputs/renewal_intelligence_output.json
5. Financial Optimization Agent -> outputs/financial_optimization_output.json
6. Scenario Comparison Agent -> outputs/scenario_comparison_output.json
7. Dashboard displays all outputs

## Quick Start
1. Create and activate a virtual environment.
2. Install dependencies:
   pip install streamlit pandas
3. Run agents in workflow order.
4. Launch UI:
   streamlit run ui/app.py

## Team Ownership
- SETH: data/*, contract_texts/*, agents/discovery_agent.py
- RYAN: ui/*, agents/waste_detection_agent.py
- JESSIE: agents/contract_intelligence_agent.py, agents/renewal_intelligence_agent.py
- SOFIA: agents/financial_optimization_agent.py, agents/scenario_comparison_agent.py, docs/*
