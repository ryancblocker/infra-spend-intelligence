# Verification Report — Agentic LLM & Reasoning Agents

**Date:** 2026-07-31
**Branch:** `sofia/agentic-llm-agents`
**Plan:** `2026-07-31-sofia-agentic-llm-agents.md`

## Status: 11 of 12 tasks complete

Task 12 (end-to-end against a real model) is **blocked** — Ollama is not
installed on this machine. Everything below was verified in `offline` mode with
a fake LLM backend, which exercises the loop mechanics but not real model
behavior.

## Test suite

```
67 passed in 0.24s
```

18 pre-existing tests still green; 49 added, all against a fake LLM backend
injected at the `llm_client` boundary. No test requires Ollama.

## Verified

| Claim | Evidence |
|---|---|
| Extraction loop terminates on completion | test: 1 iteration, 1 LLM call when all fields resolve |
| Extraction loop terminates at cap | test: stops at `MAX_EXTRACTION_ITERS`, reports unresolved |
| Iteration 2 targets only gaps | test: queries for unresolved fields present, resolved absent |
| Resolved fields never overwritten | test: first value survives contradicting later replies |
| Citations attach to real clauses | 15/15 contracts, 108 field citations, correct headings |
| Retrieval finds the right clause | 4/4 top-1 clause accuracy on C-0007 |
| Reflection loop fires and terminates | critic ran twice, `revision_count` = 1, narrator still ran |
| Revision never touches cost math | test: all 6 cost fields identical pre/post revision |
| Schema repair recovers | test: invalid JSON → validation error fed back → valid parse |
| Fallback contract preserved | test: repair exhaustion returns `None` |
| Think-tags stripped | tests on `plain_complete`, structured path, and narrator |
| Empty-after-strip falls back | test: think-only response → templated summary |
| Injection detected and surfaced | poisoned doc → 3 markers flagged, fee still 40% not 0% |
| Pipeline unchanged offline | $14,959,346 spend / $2,167,343 savings / 277 findings — matches pre-work baseline |

## Extraction accuracy — offline baseline

| Field | Correct | Total | Accuracy |
|---|---|---|---|
| `renewal_date` | 5 | 5 | 100% |
| `auto_renew` | 5 | 5 | 100% |
| `notice_period_days` | 2 | 5 | **40%** |
| `termination_fee_pct` | 5 | 5 | 100% |
| `annual_escalator_pct` | 5 | 5 | 100% |
| `minimum_commitment` | 1 | 5 | **20%** |
| `sla_summary` | 5 | 5 | 100% |
| `liability_cap_summary` | 5 | 5 | 100% |
| `has_mfn_clause` | 5 | 5 | 100% |
| `has_price_protection_clause` | 5 | 5 | 100% |
| **overall** | **43** | **50** | **86%** |

The two weak fields are where the LLM path must prove itself:

- `notice_period_days` (40%) — the regex is tuned to auto-renew phrasing and
  misses C-0021/C-0035/C-0046, which renew "by mutual written agreement … prior
  to expiration".
- `minimum_commitment` (20%) — the pattern matches one phrasing out of several.

## Corrections made during implementation

**Relevance floor used the wrong distance metric.** The spec specified `0.75`
and `0.95`, assuming cosine distance. Chroma defaults to squared L2, which on
unit-normalized vectors is a `[0, 2]` scale — so those floors rejected every
hit. Measured against C-0007: correct clauses land at 1.23–1.48, irrelevant
chunks at 2.0. Floor corrected to `1.90` for hashed embeddings, and the metric
is now pinned in `vector_store.VECTOR_SPACE` so a default change can't silently
break citation filtering.

**Per-field extraction calls were infeasible.** The first plan draft made one
LLM call per field group (~150 calls across 15 contracts). Corrected to one
call per iteration over a deduplicated union of retrieved chunks: ~15–25 calls.

## Not verified — requires Ollama

1. **Whether the LLM actually beats the 86% regex baseline.** The entire
   justification for the agentic path is unmeasured until
   `eval_extraction.py --mode ollama` runs.
2. **Whether the loop ever iterates in practice.** No contract has been observed
   with `extraction_iterations > 1` against a real model.
3. **Whether the reflection loop fires naturally.** It was verified with a
   forced flag; the critic currently raises 0 flags on real data, so it may
   never trigger on its own.
4. **Whether prompt injection is actually resisted.** Offline mode uses regex,
   which is immune by construction — detection and reporting were verified, the
   model's resistance was not.
5. **`RELEVANCE_FLOOR_EMBED = 1.50`** is a guess, unmeasured against
   `nomic-embed-text`.
6. **Wall-clock time for a full ollama run** — the key demo-feasibility number.

## Next steps

```bash
brew install ollama && ollama serve
ollama pull qwen3:8b && ollama pull nomic-embed-text
./.venv/bin/python scripts/eval_extraction.py --mode ollama
```

Then work items 1–6 above.

## Cross-team changes

Files touched outside Sofia's ownership, all small — coordinate before merge:

| File | Owner | Change |
|---|---|---|
| `app/orchestrator/graph.py` | Jessy | conditional edge for the reflection loop |
| `app/orchestrator/state.py` | Jessy | `revision_count`, `revision_requests` |
| `app/agents/schemas.py` | shared | `ClauseCitation`, `ContractTerms`, `RevisionRequest` |
| `app/main.py` | Jessy | injection delimiting in `/ask` |
| `app/config.py` | Jessy | loop caps, timeout, floors, cache paths |
| `tests/` | Ryan | new LLM-path test module + fixtures |
| `app/templates/contract_detail.html`, `theme.css` | Ryan | citations + trace UI |

## Known issue outside this work

The pipeline produces **277 findings across 336 assets** (~82%). README lines
97–99 flag that as a threshold bug. It is Seth's area and untouched here, but a
demo where four in five assets are flagged undercuts the "clear business value"
criterion.
