<!--
Purpose: Describe the operating workflow from data ingestion through executive dashboard reporting.
Inputs: Agent definitions, output contracts, and execution dependencies.
Outputs: Repeatable runbook for development, testing, and demos.
Assigned Team Member: SOFIA
Dependencies: Project README, agent scripts, and output schemas.
-->

# PACT Workflow

## Sequential Steps
1. Run Discovery Agent to generate discovery_output.json.
2. Run Waste Detection Agent to generate waste_findings.json.
3. Run Contract Intelligence Agent to generate contract_intelligence_output.json.
4. Run Renewal Intelligence Agent to generate renewal_intelligence_output.json.
5. Run Financial Optimization Agent to generate financial_optimization_output.json.
6. Run Scenario Comparison Agent to generate scenario_comparison_output.json.
7. Start Streamlit app and review results in dashboard pages.

## Suggested Commands
- python agents/discovery_agent.py
- python agents/waste_detection_agent.py
- python agents/contract_intelligence_agent.py
- python agents/renewal_intelligence_agent.py
- python agents/financial_optimization_agent.py
- python agents/scenario_comparison_agent.py
- streamlit run ui/app.py

## TODO (SOFIA)
- Add workflow automation script
- Add error handling and rollback strategy for failed stages
