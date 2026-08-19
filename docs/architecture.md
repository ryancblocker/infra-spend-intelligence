# PACT Architecture

PACT (Portfolio Agentic Contract Tracker) is a local-first, agentic infrastructure
and SaaS spend intelligence platform. It ingests a portfolio of contracts and
child assets (telecom circuits, colocation deployments, software licenses,
mobile lines), runs an eight-agent pipeline over them, and serves the results
through a custom web UI - no cloud dependency required.

## Design principles

1. **Deterministic where correctness is provable, LLM where judgment is required.**
   Totals, date math, and rate comparisons have exactly one correct answer -
   those agents are plain Python. Clause extraction from prose, negotiation
   strategy, and executive narrative benefit from language understanding -
   those agents call an LLM, with a deterministic offline fallback so the app
   never breaks when no model is configured.
2. **Local-first, cloud-optional.** The default LLM backend is a local model
   served by [Ollama](https://ollama.com). `ANTHROPIC_API_KEY` can be set for a
   cloud fallback. If neither is available, every agent still runs using its
   deterministic offline logic - the UI labels which mode produced each result.
3. **Never let the LLM invent a dollar figure.** Every cost projection (keep /
   cancel / renegotiate spend, savings, break-even) is computed in Python from
   contract terms. The LLM is only asked for judgment (action, confidence,
   rationale, talking points) - and a dedicated Critic agent re-checks those
   judgments against the underlying numbers before they reach the UI.

## Agent pipeline (LangGraph)

```
                    ┌─────────────┐
                    │  discovery  │  deterministic - portfolio totals
                    └──────┬──────┘
        ┌──────────┬───────┴───────┬──────────┐
        ▼          ▼               ▼          ▼
  ┌───────────┐┌────────┐┌──────────────┐┌──────────┐
  │extraction ││ waste  ││  benchmark   ││ renewal  │
  │ (LLM+RAG) ││(rules) ││(rules + LLM  ││(dates +  │
  │           ││        ││  narrative)  ││LLM       │
  └─────┬─────┘└───┬────┘└──────┬───────┘│narrative)│
        └───────────┴─────┬─────┴────────┴────┬─────┘
                           ▼                   
                  ┌──────────────────┐
                  │   optimization    │  cost math (Python) +
                  │  (LLM judgment)   │  action/rationale (LLM, top N)
                  └─────────┬─────────┘
                             ▼
                  ┌──────────────────┐
                  │      critic       │  numeric sanity check (always) +
                  │  (reflection)     │  LLM plausibility review (top 10)
                  └─────────┬─────────┘
                             ▼
                  ┌──────────────────┐
                  │     narrator      │  executive summary synthesis
                  └──────────────────┘
```

This follows the Orchestrator-Worker + Reflection multi-agent patterns:
Discovery fans out to four independent workers, those join into Optimization,
and a Critic (reflection) pass runs before the Narrator synthesizes the
executive summary. See `app/orchestrator/graph.py`.

| Agent | File | LLM? | What it does |
|---|---|---|---|
| Discovery | `app/agents/discovery.py` | No | Aggregates portfolio totals from SQLite |
| Extraction | `app/agents/extraction.py` | Yes | Parses contract prose into structured clauses (renewal terms, SLA, liability cap, MFN/price-protection) via RAG-grounded structured output |
| Waste | `app/agents/waste.py` | No | Utilization-threshold rules (underused circuits/colo/licenses, unassigned/inactive mobile lines, missing owners) |
| Benchmark | `app/agents/benchmark.py` | Hybrid | Rate-vs-benchmark comparisons (rules) + one market-positioning narrative (LLM) |
| Renewal | `app/agents/renewal.py` | Hybrid | Renewal risk classification from date math (rules) + one portfolio narrative (LLM) |
| Optimization | `app/agents/optimization.py` | Hybrid | 36-month keep/cancel/renegotiate cost projections (Python) + recommended action/confidence/talking points (LLM, top ~15 by value) |
| Critic | `app/agents/critic.py` | Hybrid | Deterministic sanity check on every recommendation (always on) + LLM plausibility review of the top 10 |
| Narrator | `app/agents/narrator.py` | Yes | Synthesizes the executive summary from every other agent's output |

## Data layer

- **`app/data/seed/*.csv`** - human-editable source-of-truth fixtures (contracts,
  circuits, colocation, licenses, mobile lines, benchmark rates). Generated
  once by `app/data/generate_seed_data.py`, a deterministic (seeded) synthetic
  data generator grounded in 2026 market research (see Sources below) - not
  arbitrary numbers.
- **`app/data/contract_docs/*.txt`** - 15 full-length synthetic contracts
  written as real commercial/legal prose (term & renewal, fees, termination,
  SLA credits, liability cap, and - on a subset - MFN and price-protection
  clauses), so the extraction agent has something that actually requires
  language understanding rather than key:value parsing.
- **`runtime/pact.db`** (SQLite, gitignored) - built from the CSV seeds by
  `app/data/seed_db.py`. SQLite scales to a much larger portfolio than the
  original 10-contract demo without adding a database server; swapping in
  Postgres later would only mean changing `app/tools/dataset_tools.py`.
- **`runtime/vector_store/`** (Chroma, gitignored) - contract documents chunked
  by paragraph and embedded for semantic search, powering the extraction
  agent's grounding and the `/ask` endpoint's retrieval.

## LLM backend (`app/tools/llm_client.py`)

Three modes, auto-detected at startup (`PACT_LLM_MODE` env var forces one):

1. **`ollama`** (default when reachable) - local model via `ollama` Python
   client. Chat model: `qwen3:1.7b`, sized deliberately for an 8 GB unified-
   memory Mac - `qwen3:8b` was the original design target but hung such a
   machine outright under real pipeline load (see `docs/setup.md`).
   Embedding model: `nomic-embed-text`. Both overridable via env vars.
2. **`anthropic`** - used if `ANTHROPIC_API_KEY` is set and Ollama isn't
   reachable. Structured output via forced tool-use.
3. **`offline`** - deterministic fallback (regex extraction, templated
   narratives, hashed lexical embeddings for search). Guarantees the app is
   fully functional with zero external dependencies.

Structured output uses Pydantic schemas end-to-end (`app/agents/schemas.py`):
the LLM is asked to fill a JSON schema, the response is validated with one
retry-on-invalid-JSON, and falls back to `None` (triggering the deterministic
path) on repeated failure - the pipeline never crashes because a local model
returned malformed output.

## Frontend

FastAPI + Jinja2 server-rendered pages + vanilla CSS design system + vendored
Alpine.js and Chart.js (no CDN, no Node/build step - `pip install` is the only
setup). Pipeline runs stream progress over Server-Sent Events
(`GET /api/run`), driving a live agent-pipeline visualization on the Overview
page. `/ask` is a RAG chat interface over the contract corpus.

## Known simplifications

- The pipeline runs synchronously in a worker thread per request
  (`asyncio.to_thread`) rather than a job queue - correct and simple for a
  single-user local app; a multi-user deployment would want a real task queue.
- `/api/ask` returns a complete answer rather than streaming tokens, to keep
  scope proportional to a local demo tool; token streaming would reuse the
  same SSE pattern as `/api/run`.

## Sources

Market benchmark research grounding the synthetic dataset and the overall
2026 agentic-architecture approach:

- [SirionAI - AI Impact on CLM 2026](https://www.sirion.ai/library/contract-insights/ai-contract-lifecycle-management/)
- [SitePoint - Agentic Design Patterns 2026](https://www.sitepoint.com/the-definitive-guide-to-agentic-design-patterns-in-2026/)
- [Towards AI - Local Agents 2026 (Ollama + LangGraph)](https://pub.towardsai.net/local-agents-2026-building-privacy-first-workflows-with-ollama-langgraph-6928fb63d81d)
- [Brightlio - Colocation Pricing 2026](https://brightlio.com/colocation-pricing/)
- [Socium IT - Telecom Cost Benchmarking 2026](https://www.sociumit.com/resources/blog/telecom-cost-benchmarking-2026)
- [Zylo - Agentic SaaS Management](https://zylo.com/news/agentic-saas-management/)
- [Zylo - Unifying SaaS and Consumption Spend](https://www.prweb.com/releases/zylo-launches-industry-first-solution-unifying-saas-and-consumption-spend-bringing-visibility-to-exploding-ai-and-usage-based-costs-302741363.html)
