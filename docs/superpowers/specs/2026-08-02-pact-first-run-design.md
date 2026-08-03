# Design: PACT First-Run Experience

**Date:** 2026-08-02
**Owner:** Sofia
**Status:** Approved

## Problem

Opening PACT shows a fully populated dashboard with $14.9M in spend and 277
findings already calculated, because `runtime/last_run.json` is restored at
startup. Clicking "Run Analysis" then appears to do nothing: the offline
pipeline completes in **0.02 seconds**, so the pipeline visualization flashes
and settles back to an identical screen.

Two distinct defects underneath:

1. **No entry point.** A first-time viewer has no idea what the tool is, what
   data is loaded, or what the eight agents are about to do.
2. **The agentic work is invisible.** `app/orchestrator/graph.py` emits only
   `completed` events - never `started`, despite `events.py` defining that
   status. Nodes jump grey to green with no working state. This would remain
   broken with Ollama attached: each agent would sit visually idle for 30+
   seconds, then everything would turn green at once.

For a project judged on "level of autonomy vs simple automation", a demo where
the autonomy is imperceptible is the worst possible failure mode.

## Scope

First-run experience only. **Uploading your own contracts is explicitly out of
scope** and deferred; the welcome page acknowledges it as planned so the
synthetic dataset is never presented as real.

## Component 1: `/welcome` routing

`/welcome` is a permanent explainer that doubles as the first-run entry - not a
splash screen that becomes dead weight after one use.

- `GET /` - redirects to `/welcome` when no run exists; otherwise renders the
  dashboard unchanged.
- `GET /welcome` - always renders. Before a run: primer plus a **Run Analysis**
  CTA. After a run: same explainer, CTA becomes **View Dashboard**.
- Nav gains a **How it works** link to `/welcome`, so the agent explainer stays
  reachable during Q&A without resetting anything.

## Component 2: `/welcome` content

Three blocks:

**What this is** - one paragraph: local-first agentic spend intelligence, eight
agents, runs against a local model, no data leaves the machine.

**What's loaded** - counts read live from the database via `dataset_tools`,
never hardcoded, so the page cannot drift from reality: contracts, circuits,
colocation, licenses, mobile lines, contract documents, total annual spend.
Labeled explicitly as a **synthetic sample portfolio**, with one line noting
that contract upload is planned.

**What will happen** - the eight agents as a static preview of the same pipeline
structure that animates during the run, each with a one-line description, so a
viewer knows what they are watching before it moves.

## Component 3: Making the run watchable

**Emit `started` events** (`graph.py`). A genuine bug fix: `events.py` already
supports the status and the frontend already styles a running state. Emitted
before each node executes.

Because the graph streams with `stream_mode="updates"` - which yields only
*after* a node completes - `started` cannot be derived from the stream. It is
emitted by wrapping each node function, so the event fires when the node
actually begins.

**Minimum dwell, frontend only** (`app.js`). A ~400ms floor on how briefly a
node can display its running state. Backend timings and the detail text each
node reports stay true; this only prevents rendering faster than human
perception. With Ollama, real latency exceeds the floor and it has no effect.

Offline, the pipeline becomes roughly three seconds of legible sequence instead
of a single frame. Nothing is fabricated - no fake work, no invented numbers,
no scripted replay.

## Component 4: Not starting pre-populated

- `PACT_FRESH_START=1` - skip loading a persisted run at startup. A deliberate
  demo-from-zero switch.
- **Reset** control on `/welcome` (`POST /api/reset`) - clears the in-memory run
  and deletes `runtime/last_run.json`, so the full arc can be rehearsed
  repeatedly without touching the filesystem by hand.

Persistence stays **on by default**; losing a completed run on restart would be
a regression for normal use.

## Files

| File | Change |
|---|---|
| `app/main.py` | `/welcome` route, `/` redirect, `POST /api/reset` |
| `app/templates/welcome.html` | new |
| `app/templates/base.html` | "How it works" nav link |
| `app/orchestrator/graph.py` | emit `started` per node |
| `app/static/js/app.js` | minimum dwell between node state changes |
| `app/config.py` | `FRESH_START` flag |
| `app/static/css/theme.css` | welcome page styles |

Mostly Ryan's and Jessy's areas - flag to them.

## Error handling

- Empty/missing database - welcome page renders with zero counts rather than
  erroring; the Run button still works and seeds on demand.
- `POST /api/reset` with no saved run - succeeds silently, idempotent.
- Dwell pacing is presentation-only; a slow or failed run still reports its true
  status and detail text.

## Testing

- `/` redirects to `/welcome` when no run exists
- `/` renders the dashboard when a run exists
- `/welcome` renders in both states with the correct CTA
- welcome counts match `dataset_tools` output
- `POST /api/reset` clears state and is idempotent
- pipeline emits `started` before `completed` for every node, in order
- `PACT_FRESH_START=1` leaves `has_run` false despite a persisted run on disk

## Out of scope

Contract upload, authentication, multi-tenant runs, and any change to agent
logic or thresholds.
