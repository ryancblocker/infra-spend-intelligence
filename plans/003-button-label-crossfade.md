# 003 — Crossfade "idle vs busy" button labels instead of snapping

- **Status**: TODO
- **Commit**: f3e9862
- **Severity**: LOW
- **Category**: Missed opportunity (state indication) / Interruptibility
- **Estimated scope**: 2 files (`app/templates/mission_control.html`, `app/static/css/theme.css`), 2 buttons

## Problem

Two buttons on Mission Control swap their label between an idle and a busy
state via Alpine `x-show`, with no transition — the text hard-cuts the
instant `running` flips:

```html
<!-- app/templates/mission_control.html:96-99 — current -->
<button class="btn btn-primary" @click="start()" :disabled="running">
  <span x-show="!running">{% if has_run %}Re-run Analysis{% else %}Run Analysis{% endif %}</span>
  <span x-show="running">Running…</span>
</button>
```

```html
<!-- app/templates/mission_control.html:199-202 — current -->
<button class="btn btn-ghost" @click="start()" :disabled="running">
  <span x-show="!running">Refresh market pricing</span>
  <span x-show="running">Refreshing…</span>
</button>
```

Plain `x-show` (no `x-transition`) toggles Alpine's own `display: none`
synchronously — there is no fade at all today. Both buttons are `display:
inline-flex` (`.btn`, `app/static/css/theme.css:576`), so the two `<span>`s
are flex siblings; naively adding an opacity crossfade without also
stacking them would make the button visibly widen/narrow for the swap's
duration as both labels briefly sit side-by-side in flex flow. The fix
below stacks them in one grid cell so only opacity moves.

## Target

**CSS** — new rules in `app/static/css/theme.css`, placed directly after
the existing `.scenario-card-enter`/`.scenario-card-leave` block
(`theme.css:328-334`, the only existing precedent in this file for a named
Alpine `x-transition` class pair):

```css
/* Idle/busy button labels (Run Analysis <-> Running…, Refresh market
   pricing <-> Refreshing…): a plain opacity crossfade, not a slide - the
   button itself doesn't move, only what it says. Both labels share one
   grid cell (.btn-label-stack) so the swap never widens or narrows the
   button mid-transition the way two flex siblings briefly overlapping
   would. */
.btn-label-stack { display: grid; grid-template-areas: "label"; }
.btn-label-stack > span { grid-area: label; }
.btn-label-enter, .btn-label-leave { transition: opacity var(--duration-fast) var(--ease-out); }
.btn-label-enter-start, .btn-label-leave-end { opacity: 0; }
.btn-label-enter-end, .btn-label-leave-start { opacity: 1; }
```

**HTML** — wrap each pair of spans in `.btn-label-stack` and add the same
six `x-transition:*` attributes the scenario-card pattern already uses
(`app/templates/scenarios.html:31-36`), pointed at the three new class
names above instead of the scenario-card ones:

```html
<!-- target: app/templates/mission_control.html:96-99 -->
<button class="btn btn-primary" @click="start()" :disabled="running">
  <span class="btn-label-stack">
    <span x-show="!running"
          x-transition:enter="btn-label-enter"
          x-transition:enter-start="btn-label-enter-start"
          x-transition:enter-end="btn-label-enter-end"
          x-transition:leave="btn-label-leave"
          x-transition:leave-start="btn-label-leave-start"
          x-transition:leave-end="btn-label-leave-end">{% if has_run %}Re-run Analysis{% else %}Run Analysis{% endif %}</span>
    <span x-show="running"
          x-transition:enter="btn-label-enter"
          x-transition:enter-start="btn-label-enter-start"
          x-transition:enter-end="btn-label-enter-end"
          x-transition:leave="btn-label-leave"
          x-transition:leave-start="btn-label-leave-start"
          x-transition:leave-end="btn-label-leave-end">Running…</span>
  </span>
</button>
```

```html
<!-- target: app/templates/mission_control.html:199-202 -->
<button class="btn btn-ghost" @click="start()" :disabled="running">
  <span class="btn-label-stack">
    <span x-show="!running"
          x-transition:enter="btn-label-enter"
          x-transition:enter-start="btn-label-enter-start"
          x-transition:enter-end="btn-label-enter-end"
          x-transition:leave="btn-label-leave"
          x-transition:leave-start="btn-label-leave-start"
          x-transition:leave-end="btn-label-leave-end">Refresh market pricing</span>
    <span x-show="running"
          x-transition:enter="btn-label-enter"
          x-transition:enter-start="btn-label-enter-start"
          x-transition:enter-end="btn-label-enter-end"
          x-transition:leave="btn-label-leave"
          x-transition:leave-start="btn-label-leave-start"
          x-transition:leave-end="btn-label-leave-end">Refreshing…</span>
  </span>
</button>
```

## Repo conventions to follow

- Motion tokens: `app/static/css/theme.css:79` `--duration-fast: 120ms;`
  and `theme.css:77` `--ease-out: cubic-bezier(0.16, 1, 0.3, 1);` — this is a
  fast UI microinteraction (AUDIT.md's "button press feedback" budget is
  100–160ms; a label swap is the same tier), so it uses `--duration-fast`,
  not `--duration-base`.
- Exemplar for the *mechanism* (named CSS transition classes driven by
  Alpine's six `x-transition:*` attributes): `.scenario-card-enter` /
  `.scenario-card-leave` in `theme.css:328-334`, wired up in
  `app/templates/scenarios.html:31-36`. This plan reuses that exact
  declarative pattern — new class names, same six-attribute wiring, same
  "transition class + start class + end class" structure per direction.
- The grid-stack technique (`.btn-label-stack`) is new to this file but is
  the standard, dependency-free way to crossfade two elements without a
  layout jump; it introduces no library and no JS.

## Steps

1. Open `app/static/css/theme.css`. Locate the end of the
   `.scenario-card-leave-end` rule (line 334, immediately before the
   `@media (prefers-reduced-motion: reduce)` block that currently starts at
   line 336).
2. Insert the five new rules from the Target CSS block above, with the
   comment, directly after line 334 and before the `@media` block.
3. Open `app/templates/mission_control.html`. Locate lines 96-99 (the
   `btn btn-primary` "Run Analysis" button) and replace the two bare
   `<span x-show="...">...</span>` lines with the wrapped, attributed
   version shown in Target — keep the `{% if has_run %}...{% endif %}`
   Jinja conditional exactly as it is inside the first span's text content.
4. Locate lines 199-202 (the `btn btn-ghost` "Refresh market pricing"
   button) and apply the same wrapping/attributing shown in Target.
5. Do not touch any other button in this file (`Reset to baseline` at line
   198, `Choose a file` at `mission_control.html:67`, etc.) — only the two
   buttons whose label already toggles via `x-show="running"`/`"!running"`.

## Boundaries

- Do NOT touch `app/static/js/app.js` — `pipelineRunner()` and
  `benchmarkRefresher()`'s `running` boolean already drive this; no JS
  changes are needed.
- Do NOT add `x-transition` to any other element in `mission_control.html`
  (e.g. the `x-show="log.length > 0"` block at line 226 — that is a
  different finding, see plan 004).
- Do NOT change `--duration-fast` or `--ease-out`, and do NOT invent a new
  duration/easing token.
- Do NOT add a `transform`/scale to this crossfade — AUDIT.md's guidance for
  a fast, non-spatial state swap is opacity only; a scale here would read as
  more motion than the moment deserves.
- If the current content of either button (quoted in Problem above) has
  drifted from what's in the file, STOP and report instead of guessing.

## Verification

- **Mechanical**: no build step for this repo. Confirm
  `app/templates/mission_control.html` still renders — start the dev server
  and load `/` without a 500 error. Confirm the CSS still parses:
  `python3 -c "s=open('app/static/css/theme.css').read(); assert s.count('{')==s.count('}')"`.
- **Feel check**:
  1. Start the dev server, open `/`, enable Demo Mode (so the pipeline
     finishes in a couple seconds instead of minutes).
  2. Click "Run Analysis" (or "Re-run Analysis"). Confirm the label
     crossfades to "Running…" — both texts briefly overlap in place with no
     visible width change in the button — rather than snapping.
  3. Confirm the reverse: when the pipeline finishes and `running` goes back
     to `false`, the label crossfades back (this will be brief since Demo
     Mode is fast; if needed, watch in DevTools' Animations panel at 10%
     playback instead of real time).
  4. Repeat for the "Refresh market pricing" / "Refreshing…" button under
     Market Pricing.
  5. In DevTools' Animations panel, set playback to 10% and confirm: the
     button's width does not visibly change during the crossfade (the grid
     stack is working), and the two spans' opacities move in the same
     ~120ms window, not staggered.
  6. Click "Run Analysis" then immediately click it again if still visible
     before it disables (or resize/interact rapidly) — since this uses CSS
     transitions (not keyframes) via Alpine's `x-transition`, confirm there
     is no flash-of-wrong-state or stuck-at-50%-opacity glitch if state
     flips quickly.
  7. Toggle `prefers-reduced-motion` (Rendering panel). This crossfade is
     opacity-only with no movement, so per AUDIT.md's accessibility
     guidance ("keep transitions that aid comprehension, remove position
     changes") it is intentionally left running unchanged under reduced
     motion — confirm it still crossfades and that no reduced-motion
     override was added for `.btn-label-enter`/`.btn-label-leave`.
- **Done when**: both buttons crossfade their idle/busy label over
  `--duration-fast` with `--ease-out`, the button never changes width during
  the swap, and the wiring exactly mirrors the six-attribute
  `x-transition:*` pattern already used for scenario cards.
