# PACT demo runbook

Written 2026-08-03, for the Thursday presentation. Every number here was
measured on this machine, not estimated.

> **Update, 2026-08-26:** Demo Mode (the sidenav toggle) now covers contract
> upload too, not just the pipeline run - see "The one piece of dead air"
> below. `docs/demo-assets/sample-contract.pdf` is a ready-to-use synthetic
> contract for showing off the upload path without waiting on a real one.

## Before you start (10 min ahead)

1. **Free memory.** This is an 8 GB machine and the model holds ~1.9 GB.
   Quit Chrome tabs you don't need, Keynote, Google Drive. Screen-sharing
   software takes its own share. Check headroom:

   ```
   memory_pressure | tail -2
   ```

   Below ~30% free, expect stalling. Running the model and a browser and a
   screen share on 8 GB is the tightest constraint in this demo.

2. **Start Ollama** with the concurrency caps — these are read by the server
   process, so starting Ollama from the menu-bar app silently drops them:

   ```
   OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_KEEP_ALIVE=60s ollama serve
   ```

3. **Warm the model** so the first demo call isn't a cold load:

   ```
   curl -s localhost:11434/api/chat -d '{"model":"qwen3:1.7b","messages":[{"role":"user","content":"ready"}],"stream":false}' > /dev/null
   ```

4. **Start the app in demo mode.** `PACT_FRESH_START=1` opens with nothing
   calculated, so the pipeline reveals the numbers instead of spoiling them:

   ```
   PACT_FRESH_START=1 .venv/bin/uvicorn app.main:app --port 8000
   ```

5. **Confirm the caches are warm** — this is what keeps the run at ~71s
   instead of ~4 min:

   ```
   ls -la runtime/scenario_cache.json runtime/extraction_cache.json
   ```

   If either is missing, run the pipeline once before presenting.

## Measured timings

| Action | Time | Notes |
|---|---|---|
| Pipeline run, warm caches | **71s** | What you'll show. Visible agent-by-agent progress. |
| Pipeline run, cold caches | 4.2 min | Only if caches were cleared. |
| Pipeline run, Ollama down | **0s** | Deterministic fallback. Still produces all 277 findings. |
| Contract upload | **60-75s** (real model) / **instant** (Demo Mode) | Progress bar + elapsed counter on the real path. See below. |
| `/ask` question | ~43s | Works, but slow. Ask one question, not three. |

## The one piece of dead air

An upload takes 60-75 seconds against the real model. There is a progress
bar and an elapsed counter, but it is still a minute of silence in front of
an audience.

**As of 2026-08-26, the actual fix: turn on Demo Mode first.** It forces the
same offline deterministic path onto the upload's extraction that it
already forces onto the pipeline run - no LLM call, no wait. Toggle it in
the sidenav, drag in `docs/demo-assets/sample-contract.pdf` (a synthetic
contract that reads cleanly through every extracted field - vendor,
renewal date, notice period, termination fee, escalator, SLA, liability
cap, MFN/price-protection clauses, minimum commitment), then hit "Re-run
Analysis" so the pipeline's own extracted-clauses view picks it up too.
Whole loop is a few seconds.

The options below are for when you specifically want the *real* model
demonstrated on upload (e.g. someone asks "does this actually call the
LLM?") rather than the fast path:

**Options, in order of preference:**
1. Upload *before* you present, then show the result and re-run the
   pipeline live. The pipeline is the more impressive part anyway.
2. Upload live and talk over it — explain what the extraction agent is
   doing (retrieve clauses, check its own gaps, query again for what's
   still missing) while it runs. The wait becomes the explanation.
3. Don't upload live at all; show it as a screenshot.

## If something breaks

- **Ollama dies or won't start** — do nothing. `LLM_MODE=auto` detects it and
  falls back to the deterministic path automatically. Every page works and
  the pipeline runs in 0s. Verified 2026-08-03 with Ollama unreachable.
- **The app freezes during upload** — it shouldn't; that was fixed. If it
  does, the upload still completes; wait it out rather than reloading.
- **Machine starts swapping hard** — quit the browser, restart Ollama. Do not
  switch to a larger model: `qwen3:8b` hangs this laptop outright.

## Be ready for these questions

**"Did your agent analyse all 277 findings?"**
No, and the scenarios page says so. The model reasons about the highest-impact
findings (8 in the last run, capped at 15); the rest use the deterministic
rule engine. Every finding gets a scenario — none are dropped. Cost figures
are *always* computed in Python, never by the model, on every path.

**"How well does the extraction actually work?"**
Measured, in `runtime/eval_extraction_*.md`: the offline regex scores 86%
against hand-labeled ground truth, `qwen3:1.7b` scores 44%. Say this plainly
— it's a stronger answer than claiming success. The nuance that makes it
interesting: the regexes are tuned to the phrasing of our own seed generator,
so 86% does not predict performance on a real contract. The two fields the
model *wins* — notice period (80% vs 40%) and minimum commitment (40% vs 20%)
— are exactly the ones where real contracts vary in wording.

**"Why such a small model?"**
8 GB of unified memory. `qwen3:8b` needs ~5.2 GB resident and hard-hung this
machine twice on 2026-08-02. The architecture is model-agnostic —
`--mode anthropic` is wired through `llm_client.py` — the constraint is
hardware, not design.

**"What happens on a scanned PDF?"**
Rejected with a message naming OCR as the reason, rather than silently
creating a contract with no terms. Same for empty files, oversized files, and
unsupported types. Try it live: `~/Desktop/pact-test-contracts/` has files
that trigger each path.

## Don't do this on Thursday

- Don't switch models.
- Don't clear `runtime/` — you lose both warm caches.
- Don't run the test suite mid-demo (it reseeds a temporary database, which is
  safe, but it's a distraction).
- Don't add features between now and then. Everything currently in the branch
  has been reviewed; anything added now hasn't been.
