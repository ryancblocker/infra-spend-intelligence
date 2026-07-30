<!--
Purpose: Define the technical architecture of PACT including agent boundaries and data flow.
Inputs: Product requirements, team responsibilities, and workflow stages.
Outputs: Shared architecture reference for implementation and demo alignment.
Assigned Team Member: SOFIA
Dependencies: Markdown documentation tooling and repository source structure.
-->

# PACT Architecture

## System Components
- Data layer: CSV datasets and unstructured contract text files
- Agent layer: six sequential intelligence agents
- Output layer: JSON artifacts per agent
- Presentation layer: Streamlit control tower UI

## Data Flow
1. Discovery consolidates assets and spend.
2. Waste Detection identifies utilization inefficiencies.
3. Contract Intelligence parses key clauses.
4. Renewal Intelligence surfaces notice deadlines and risks.
5. Financial Optimization generates strategy recommendations.
6. Scenario Comparison quantifies keep vs cancel vs renegotiate.
7. UI reads all outputs and renders executive insights.

## TODO (SOFIA)
- Add orchestration diagram and async processing model
- Define model interfaces for future LLM integrations
- Add data quality and governance controls
