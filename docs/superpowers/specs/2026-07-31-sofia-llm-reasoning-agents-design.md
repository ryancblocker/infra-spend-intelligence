# Design: LLM & Reasoning Agents — Bounded Autonomy + Provenance

**Date:** 2026-07-31
**Owner:** Sofia (LLM & Reasoning Agents)
**Status:** Approved for planning

## Problem

PACT's LLM area works but is not agentic. Every model call is one-shot: prompt
in, JSON out, no iteration, no tool use, no self-correction. The pipeline is a
fixed DAG that always executes the same eight nodes in the same order. Nothing
in the system decides anything.

Three concrete gaps against the area's stated responsibilities (README
lines 109-142):

1. **RAG is not wired into extraction.** `vector_store` is imported only by
   `app/main.py` for index building and `/ask`. `extraction.py:32` reads whole
   files off disk. Half the stated retrieval responsibility is unimplemented.
2. **No prompt-injection defense.** `extraction.py:44` interpolates raw
   contract text directly into the user message; `main.py:175` does the same
   with retrieved chunks. A contract containing instructions gets obeyed.
3. **Silent failure.** `chat_structured` swallows every exception and returns
   `None`, so a working LLM path is indistinguishable from one that has never
   succeeded. There is zero test coverage on any LLM-backed code path.

## Constraints

- **Backend: local Ollama, `qwen3:8b`.** No API keys available. Ollama is not
  yet installed on the dev machine.
- **Timeline: a few days.**
- **Judging rubric:** Impact & values 25, Feasibility & practicality 25,
  Innovation & creativity 20, AI usage & agentic thinking 20, Clarity &
  storytelling (remainder). Explicitly assessed: *"level of autonomy vs simple
  automation"*, *"scalability and maintainable solution"*, *"realistic
  implementation within constraints"*.
- Hardcoded/cached demo data is permitted.

Half the rubric is impact plus feasibility. The design therefore optimizes for
*demonstrable autonomy that reliably runs on a small local model*, not for
maximum agent complexity.

## Core design principle

**Deterministic loop control, LLM reasoning inside each step.**

`qwen3:8b` cannot reliably decide "have I finished?" but it can reliably answer
"what does this clause say?". So loop *termination* is computed in Python from
observable state, while each *step* inside the loop is model reasoning. This
yields genuine autonomy — the agent's next action is a function of its own
previous result — with a hard guarantee of termination.

Every LLM path degrades to the current deterministic behavior on failure. The
app must never hard-crash because a local model is slow, absent, or wrong.

---

## Component 1: Agentic extraction loop (`app/agents/extraction.py`)

Replaces the one-shot whole-file read with a bounded investigation loop, run
per contract:

```
retrieve(field group) -> extract -> assess gaps -> targeted re-retrieve -> merge -> done
```

### Loop specification

- `MAX_EXTRACTION_ITERS = 3`
- **Iteration 1 — one LLM call.** Run every field query in the map below
  against `vector_store` scoped to this `contract_id` (`k=3` each), take the
  **union of retrieved chunks deduplicated by `chunk_index`**, and make a
  single extraction call over the full `ContractTerms` schema using that
  assembled context.
- **Gap assessment (deterministic, no LLM call):** a required field is
  unresolved if it is `None`, `""`, or — for the two boolean clause-presence
  fields — was not supported by any retrieved chunk above the relevance floor.
- **Iterations 2..N — one LLM call each.** The agent constructs *its own*
  targeted retrieval queries for only the still-unresolved fields, retrieves
  against those, and makes a single extraction call using a dynamically
  narrowed schema (`pydantic.create_model` over the unresolved subset).
  Results merge into the accumulating record; already-resolved fields are
  never overwritten.

**Call budget:** one call per iteration, not one per field. Most contracts
resolve in iteration 1, so the expected cost is ~15-25 LLM calls for the full
15-document corpus — tractable on `qwen3:8b`. A per-field call design would be
~150 calls and is explicitly rejected as infeasible on this hardware.
- **Terminate** when no unresolved required fields remain, or the iteration cap
  is reached. Whatever is still unresolved is reported as unresolved — not
  guessed.

The autonomy claim rests on iteration 2+: the query issued is computed from the
agent's own assessment of its own prior output. Nothing scripts it.

### Field → retrieval query map

| Field | Query |
|---|---|
| `renewal_date` | term expiration end date renewal |
| `auto_renew` | automatically renew successive terms |
| `notice_period_days` | written notice of non-renewal days prior |
| `termination_fee_pct` | early termination fee penalty for convenience |
| `annual_escalator_pct` | annual escalator price increase uplift anniversary |
| `minimum_commitment` | minimum commitment volume covered services |
| `sla_summary` | service level credits availability uptime |
| `liability_cap_summary` | limitation of liability aggregate cap |
| `has_mfn_clause` | most favored pricing customer |
| `has_price_protection_clause` | price protection unit pricing shall not increase |

### Why retrieval on 2KB documents

The sample contracts are ~2KB and fit trivially in context, so retrieval is not
strictly required *for these documents*. It is still the right design:

- **Scalability** is an explicitly judged criterion; retrieval-first extraction
  is what lets this work on real 40-page MSAs without change.
- **Accuracy on a small model** improves when irrelevant context is removed —
  a narrow schema over 2-3 relevant clauses beats a 15-field schema over a
  whole document on an 8B model.
- It produces **genuine per-field citations**, which whole-file extraction
  cannot.

This tradeoff should be stated honestly in the demo rather than overclaimed.

### Schema split (important)

`ExtractedContract` is currently used both as the LLM output schema *and* the
state/UI record. These get separated:

- **`ContractTerms`** — LLM-facing, narrow: the clause fields only. This is
  what gets handed to `chat_structured`.
- **`ExtractedContract`** — state-facing: `ContractTerms` fields plus
  provenance and trace, assembled by orchestration code, never by the model.

The model is never asked to emit its own citations, iteration count, or
confidence bookkeeping — an 8B model does that badly, and it is all derivable
in code. This is what keeps the provenance trustworthy.

### New provenance fields on `ExtractedContract`

```python
field_sources: dict[str, ClauseCitation]   # field name -> the chunk it came from
extraction_iterations: int
unresolved_fields: list[str]
injection_flags: list[str]
```

with

```python
class ClauseCitation(BaseModel):
    contract_id: str
    chunk_index: int
    heading: str = ""
    excerpt: str = ""      # truncated, for UI display
```

### Offline fallback

The existing regex `_extract_offline` is retained unchanged as the fallback and
as the eval-harness baseline. In offline mode the loop still runs — retrieval
uses hashed embeddings and extraction uses regex — so the trace and citations
exist in every mode.

---

## Component 2: Critic → Optimization correction loop

Today `critic.py` is a dead end: it flags problems and downgrades confidence,
but nothing is ever regenerated. This becomes a real reflection loop.

### Loop specification

- `MAX_REVISIONS = 1`
- Critic runs its deterministic numeric checks plus optional LLM review.
- If any scenario carries a `warning` or `error` flag **and**
  `revision_count < MAX_REVISIONS`, a conditional edge routes back to
  Optimization carrying `revision_requests: list[RevisionRequest]`.
- Optimization regenerates **only** the flagged scenarios, with the critique
  text included in the prompt, and merges them back into the full scenario
  list.
- Critic re-checks. Cap enforced by `revision_count`, incremented in the
  optimization node.

### Non-negotiable constraint

The revision loop regenerates **judgment only** — `recommended_action`,
`business_rationale`, `negotiation_talking_points`, `confidence`. It never
regenerates numbers. All cost projections stay in `_cost_scenarios`, computed
deterministically from contract terms. This preserves the existing
anti-hallucination discipline, which is the strongest thing about the current
optimization agent.

The deterministic numeric sanity check in `_numeric_sanity_check` remains
always-on and authoritative in every mode, including offline.

### Graph changes

```python
graph.add_conditional_edges(
    "critic", route_after_critic, {"revise": "optimization", "done": "narrator"}
)
```

`optimization_node` reads `revision_requests` from state; when present it runs
in partial-regeneration mode instead of a full run.

**This is outside Sofia's ownership** (`graph.py`, `state.py` are Jessy's).
Coordinate before merging.

---

## Component 3: `llm_client.py` hardening

### Think-tag stripping

`qwen3:8b` is a reasoning model and emits `<think>...</think>` blocks.
`plain_complete` currently returns raw content, so the narrator's executive
summary will render the model's internal monologue. Strip think blocks from all
free-text completions before returning.

### Structured logging

Replace silent `except Exception: return None` with a record appended to
`runtime/llm_calls.jsonl` per call:

```
{ts, agent, mode, model, attempt, ok, latency_ms, error_class, prompt_chars, output_chars}
```

Failures still return `None` — the fallback contract is unchanged — but they
become observable. This is what makes it possible to prove the LLM path works
rather than assert it, and it directly serves the maintainability criterion.

### Timeouts

Per-call timeout (default 120s, configurable via `config`) so a hung local
model degrades to the deterministic path instead of freezing the pipeline.

### Symmetric, error-aware repair

The Anthropic path gains the retry the Ollama path already has. Both repair
attempts feed pydantic's actual `ValidationError` text back to the model rather
than a generic "that was not valid JSON", which materially improves recovery on
small models.

### Prompt-injection defense

Sofia's explicit responsibility (README line 132). Two layers:

1. **Delimiting.** All untrusted contract text is wrapped in explicit data
   delimiters, with a system-prompt rule that content inside is data to be
   analyzed and never instructions to follow. Applied in `extraction.py` and
   in the `/ask` context assembly in `main.py`.
2. **Detection.** Retrieved chunks are scanned for injection markers
   (`ignore previous`, `ignore all prior`, `system:`, `new instructions`,
   `disregard the above`). A hit raises a `CriticFlag` and is recorded in
   `injection_flags` — surfaced, not silently trusted.

A deliberately poisoned contract document is added as a test fixture (not to
the demo seed set) to prove the defense fires.

---

## Component 4: `vector_store.py`

- **Clause-aware chunking.** Replace the blind `"\n\n"` split with a split on
  the documents' numbered/headed section pattern (`1. TERM AND RENEWAL.`,
  `4. Service Level Credits:`), keeping each heading attached to its body.
  Preamble text before section 1 becomes its own chunk.
- **Heading in metadata**, so citations render as `[C-0012 §3 TERMINATION]`
  rather than a bare contract id.
- **Relevance floor** on `search()` so weak matches are never cited. `search()`
  gains a `max_distance: float | None` parameter; hits above it are dropped.
  Because cosine distances from `nomic-embed-text` and from the hashed
  fallback are not on the same scale, the default lives in `config` as two
  values — `RELEVANCE_FLOOR_EMBED = 0.75` and `RELEVANCE_FLOOR_HASHED = 0.95`
  — selected by which embedding path produced the vector. Both are starting
  values to be checked against real retrieval output during implementation and
  adjusted if they drop known-good clauses.
- The hashed-embedding fallback is retained and is labeled as such in traces —
  it is keyword-ish, not semantic, and the eval harness should not present it
  as equivalent.

---

## Component 5: Feasibility & evidence

### Extraction cache

`runtime/extraction_cache.json`, keyed by
`(contract_id, sha256(document_text), model_name)` → serialized
`ExtractedContract`. Repeat demo runs are near-instant; changing a document or
model invalidates cleanly. Bypassable via a config flag for eval runs.

This is the legitimate form of "hardcoding for the demo": real output from a
real run, cached, with a key that guarantees it matches the current inputs.

### Eval harness

`scripts/eval_extraction.py`:

- Hand-labeled ground truth for 5 of the 15 contracts
  (`tests/fixtures/extraction_ground_truth.json`).
- Runs extraction in `offline` and in `ollama` mode with the cache bypassed.
- Scores per-field exact match for scalars, presence match for booleans.
- Emits a markdown table: field, offline accuracy, ollama accuracy, delta.

This is the artifact answering the README's standing question for this area —
whether the real LLM path is a genuine improvement over the offline fallback or
just slower. It is also the single most rubric-effective deliverable for
feasibility and technical depth, because it is *evidence* rather than a claim.

### Tests (`tests/test_llm_agents.py`)

All against a **fake LLM backend** injected at the `llm_client` boundary, so
the suite runs offline, fast, and without Ollama:

- extraction loop stops when all required fields resolve in iteration 1
- extraction loop stops at `MAX_EXTRACTION_ITERS` when fields never resolve
- iteration 2 queries target *only* unresolved fields
- resolved fields are not overwritten by later iterations
- `field_sources` is populated for every resolved field
- injection markers in a retrieved chunk raise a flag and populate
  `injection_flags`
- `<think>` blocks are stripped from `plain_complete` output
- schema repair path: invalid JSON then valid JSON returns the valid model
- schema repair exhaustion returns `None` (fallback contract preserved)
- critic routes to `revise` on a warning flag, to `done` at the revision cap
- revision regenerates judgment fields but leaves all cost numbers identical

---

## Data flow

```
contract .txt
  -> vector_store: clause-aware chunks + headings + embeddings
  -> extraction loop: retrieve -> extract -> assess -> re-retrieve (<=3)
  -> ExtractedContract + field_sources + unresolved_fields + injection_flags
  -> state

waste findings + benchmark findings
  -> optimization: deterministic cost math + LLM judgment (top-15 high-value)
  -> critic: numeric checks (always) + LLM review
  -> [flags && revision_count < 1] -> optimization (judgment-only regeneration)
  -> narrator: executive summary (think-tags stripped)
  -> PipelineRunSummary
```

## Error handling

| Failure | Behavior |
|---|---|
| Ollama absent/unreachable | `get_mode()` resolves `offline`; regex extraction, templated narrative |
| Model returns invalid JSON | Error-aware repair retry, then `None` → deterministic fallback |
| Model hangs | Per-call timeout → `None` → deterministic fallback |
| Retrieval returns nothing above floor | Field marked unresolved; never guessed |
| Injection marker detected | `CriticFlag` raised, recorded, text still treated as data |
| Revision loop | Hard-capped at `MAX_REVISIONS = 1` |
| Extraction loop | Hard-capped at `MAX_EXTRACTION_ITERS = 3` |

## Files changed

**Sofia's area:** `app/agents/extraction.py`, `optimization.py`, `critic.py`,
`narrator.py`, `app/tools/llm_client.py`, `app/tools/vector_store.py`

**Outside — coordinate with the team:**

| File | Owner | Change |
|---|---|---|
| `app/orchestrator/graph.py` | Jessy | conditional edge for the critic loop |
| `app/orchestrator/state.py` | Jessy | `revision_count`, `revision_requests` |
| `app/agents/schemas.py` | shared | `ClauseCitation`, `ContractTerms`, provenance fields |
| `app/main.py` | Jessy | injection delimiting in `/ask` context assembly |
| `app/config.py` | Jessy | loop caps, timeout, relevance floor, cache flag |
| `tests/` | Ryan | new LLM-path test module |
| `app/templates/contract_detail.html` | Ryan | surface citations + trace (if time) |

## Out of scope

- Changes to the four deterministic agents (`discovery`, `waste`, `benchmark`,
  `renewal`) — Seth's area, and their logic is sound.
- Any change to how cost projections are computed.
- Wiring `ExtractedContract` terms into `renewal.py`'s date math. This is a
  real integration gap and would strengthen the product, but it changes Seth's
  agent days before a deadline. Recorded here as the top follow-up.
- Anthropic-path tuning beyond the symmetric retry — no API key is available.

## Risks

| Risk | Mitigation |
|---|---|
| `qwen3:8b` too slow for 15 contracts × up to 3 iterations | Narrow per-group schemas keep outputs small; extraction cache makes repeat runs instant; iteration 1 resolves most fields so 2-3 are rare |
| Small model fails structured output repeatedly | Error-aware repair, then deterministic fallback; the eval harness quantifies how often this happens rather than hiding it |
| Two loops is ambitious for the timeline | Both degrade to current one-shot behavior; the critic loop is the smaller of the two and can ship alone if extraction runs long |
| Cross-file edits collide with teammates | Changes outside Sofia's area are enumerated above and are small; coordinate before merge |

## Priority

1. `llm_client` hardening (think-tags, logging, timeout, repair, injection) — everything else depends on it
2. Agentic extraction loop + provenance
3. Critic → Optimization revision loop
4. Extraction cache
5. Clause-aware chunking
6. Eval harness
7. Test suite
8. UI surfacing of citations and trace
