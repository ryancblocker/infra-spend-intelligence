# 004 — Animate new lines entering the market-pricing refresh log

- **Status**: TODO
- **Commit**: f3e9862
- **Severity**: LOW
- **Category**: Missed opportunity (feedback) / Interruptibility
- **Estimated scope**: 2 files (`app/static/js/app.js`, `app/templates/mission_control.html`), 1 function + 1 template block

## Problem

During a "Refresh market pricing" run, `benchmarkRefresher()` prepends a new
status line to `log` every time a source reports in:

```js
/* app/static/js/app.js:216-237 — current */
function benchmarkRefresher() {
  return {
    running: false,
    log: [],
    _source: null,

    start() {
      if (this.running) return;
      this.running = true;
      this.log = [];

      const source = new EventSource("/api/refresh-benchmarks");
      this._source = source;

      source.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        if (data.status === "started") {
          this.log.unshift(`${data.label}: checking…`);
        } else {
          this.log.unshift(`${data.label}: ${data.detail || data.status}`);
        }
      };
```

The list is rendered with `x-for` and **no `:key`**, over an array of plain
strings:

```html
<!-- app/templates/mission_control.html:226-230 — current -->
<div x-show="log.length > 0" style="max-height:160px; overflow-y:auto; font-size:13px; line-height:1.7;">
  <template x-for="line in log">
    <div x-text="line"></div>
  </template>
</div>
```

Two problems compound here:

1. **No entrance at all** — new lines just appear at the top of the list.
   This is the exact "Discovery: found 48 contracts" / "Waste agent:
   flagged 12 findings" *kind* of progressive status feed the pipeline
   diagram elsewhere in this same file gives motion to (`.pipeline-node-dot`
   pop on status change) — the benchmark log is the one status feed in the
   app with zero motion.
2. **No stable identity** — because `log` holds plain strings and `x-for`
   has no `:key`, Alpine cannot tell "a new line was inserted at the front"
   apart from "every line's text changed by one position." Without a key,
   any entrance animation applied to the `<template>`'s element would either
   fire on every existing line every time (wrong — it would look like the
   whole list refreshes on each event) or not fire at all. This has to be
   fixed before any transition can be added correctly.

## Target

**JS** — give each log entry a stable, unique id so Alpine can key on it:

```js
/* target: app/static/js/app.js, benchmarkRefresher() */
function benchmarkRefresher() {
  return {
    running: false,
    log: [],
    _logSeq: 0,
    _source: null,

    start() {
      if (this.running) return;
      this.running = true;
      this.log = [];

      const source = new EventSource("/api/refresh-benchmarks");
      this._source = source;

      source.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        const text = data.status === "started"
          ? `${data.label}: checking…`
          : `${data.label}: ${data.detail || data.status}`;
        this.log.unshift({ id: ++this._logSeq, text });
      };
```

**HTML** — key the loop on `entry.id`, read `entry.text`, and reuse the
existing `.msg-enter` entrance class verbatim (defined at
`app/static/css/theme.css:319-323` for the Ask page's chat messages — same
situation: a fresh DOM node from an Alpine `x-for`, no JS mount-tracking
needed once the node is genuinely new):

```html
<!-- target: app/templates/mission_control.html:226-230 -->
<div x-show="log.length > 0" style="max-height:160px; overflow-y:auto; font-size:13px; line-height:1.7;">
  <template x-for="entry in log" :key="entry.id">
    <div class="msg-enter" x-text="entry.text"></div>
  </template>
</div>
```

No new CSS is required — `.msg-enter` and its `@keyframes message-in`
already exist:

```css
/* app/static/css/theme.css:319-323 — already exists, reused as-is */
.msg-enter { animation: message-in var(--duration-base) var(--ease-out); }
@keyframes message-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
```

That keyframe is already excluded under reduced motion:

```css
/* app/static/css/theme.css — already exists, inside @media (prefers-reduced-motion: reduce) */
.msg-enter { animation: none; }
```

## Repo conventions to follow

- Exemplar for the exact pattern (Alpine `x-for` producing genuinely new
  DOM nodes, each animated on mount via a shared CSS keyframe class): the
  Ask page's chat feed, `app/templates/ask.html:21-22` —
  `<template x-for="(m, i) in messages" :key="i"><div class="msg-enter" ...>`.
  This plan's `:key="entry.id"` plays the same role `:key="i"` plays there;
  `entry.id` is needed here specifically (instead of the array index)
  because entries are inserted at the *front* (`unshift`) rather than
  appended at the end (`push`) — an index key would misidentify which item
  is actually new once existing items shift down a position.
- Motion tokens: none new — `.msg-enter` already uses
  `var(--duration-base)` / `var(--ease-out)` (`theme.css:79`, `:77`).
- `_logSeq` follows the existing underscore-prefixed-internal-field
  convention already used in this same object (`_source`) and in
  `pipelineRunner()` (`_queue`, `_draining`, `_finished`, `_started`).

## Steps

1. Open `app/static/js/app.js`. In `benchmarkRefresher()` (starts at line
   216), add `_logSeq: 0,` as a new field in the returned object, next to
   the existing `_source: null,` line (line 220).
2. Replace the `source.onmessage` handler body (lines 230-237) with the
   target version shown above: compute `text` once via a ternary (same
   branching logic as today, just assigned to a variable instead of two
   separate `unshift` calls), then `this.log.unshift({ id: ++this._logSeq, text });`.
3. Leave `start()`'s `this.log = [];` (line 225) unchanged — resetting to an
   empty array on each new run is still correct; `_logSeq` is intentionally
   *not* reset, so ids stay unique even across multiple refreshes in one
   page load.
4. Open `app/templates/mission_control.html`. Replace lines 227-229
   (the `<template x-for="line in log">` block) with the target version:
   add `:key="entry.id"` to the `<template x-for="entry in log">` tag, add
   `class="msg-enter"` to the inner `<div>`, and change `x-text="line"` to
   `x-text="entry.text"`.
5. Do not touch `app/static/css/theme.css` — `.msg-enter` and its keyframe
   and reduced-motion override already exist and need no changes.

## Boundaries

- Do NOT touch `pipelineRunner()` or any other function in `app/static/js/app.js`.
- Do NOT touch the `resetBaseline()` method or the `result`/`error` event
  listeners in `benchmarkRefresher()` — only `onmessage` and the new
  `_logSeq` field.
- Do NOT touch `app/static/css/theme.css`.
- Do NOT change how `log.length > 0` gates the wrapping `<div>`'s
  visibility (`mission_control.html:226`) — that stays as-is.
- If `benchmarkRefresher()` or the log template block no longer match the
  excerpts quoted above (drift since commit `f3e9862`), STOP and report
  instead of improvising a different key strategy.

## Verification

- **Mechanical**: `node --check app/static/js/app.js` should exit 0. Confirm
  `mission_control.html` still renders — start the dev server, load `/`,
  expect no 500.
- **Feel check**:
  1. Start the dev server, open `/`, scroll to "Market Pricing", click
     "Refresh market pricing".
  2. Confirm each new status line fades + rises in at the top of the log
     (`opacity 0→1`, `translateY(6px)→0`) instead of appearing instantly —
     the same motion the Ask page's chat messages already use.
  3. Confirm existing lines already in the log do **not** re-animate when a
     new one is added above them — only the genuinely new line plays the
     entrance. (This is the check that the `:key="entry.id"` fix is
     actually working; without it, either nothing would animate or every
     line would replay the animation on every event.)
  4. In DevTools' Animations panel, set playback to 10% while triggering a
     refresh and confirm the fade+rise is clearly visible and takes
     `--duration-base` (200ms).
  5. Toggle `prefers-reduced-motion` (Rendering panel), refresh again, and
     confirm lines still appear (just without the animation) — this reuses
     `.msg-enter`'s existing reduced-motion override
     (`.msg-enter { animation: none; }`), so no new accessibility work
     should be needed; just confirm it actually applies here too.
  6. Trigger a refresh against a source that returns quickly followed by
     one that's slow (naturally occurs since sources report at different
     speeds) and confirm rapid back-to-back inserts each still get their
     own distinct entrance rather than jank or a stuck 50%-opacity row.
- **Done when**: new benchmark-refresh log lines fade+rise in using the
  existing `.msg-enter` class with no new CSS, keyed correctly by
  `entry.id` so only genuinely new lines animate, and reduced motion is
  already handled via the pre-existing `.msg-enter` override.
