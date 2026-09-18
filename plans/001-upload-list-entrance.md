# 001 — Fade+slide entrance for newly-uploaded contract rows

- **Status**: TODO
- **Commit**: f3e9862
- **Severity**: MEDIUM
- **Category**: Missed opportunity (spatial consistency / preventing a jarring change)
- **Estimated scope**: 1 file (`app/static/js/app.js`), 1 function

## Problem

On the Mission Control page, uploading a contract calls `addRow()` in
`app/static/js/app.js:368-410`, which builds a new `<li>` with
`document.createElement` and appends it to `#upload-list` with a plain
`appendChild` — it appears instantly, with no transition:

```js
/* app/static/js/app.js:368-410 — current */
function addRow(payload) {
  let list = document.getElementById("upload-list");
  if (!list) {
    const empty = document.getElementById("upload-list-empty");
    list = document.createElement("ul");
    list.id = "upload-list";
    list.className = "upload-list";
    if (empty) {
      empty.replaceWith(list);
    } else {
      status.insertAdjacentElement("afterend", list);
    }
  }
  const li = document.createElement("li");
  li.dataset.contractId = payload.contract_id;
  const link = document.createElement("a");
  link.href = `/contracts/${payload.contract_id}`;
  link.textContent = payload.contract_id;
  const vendor = document.createElement("span");
  vendor.className = "upload-vendor";
  vendor.textContent = payload.vendor || payload.original_filename || "";
  const renewal = document.createElement("span");
  renewal.className = "upload-renewal";
  renewal.textContent = payload.renewal_date || "";
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "btn btn-ghost btn-remove";
  remove.dataset.remove = payload.contract_id;
  remove.textContent = "Remove";
  li.append(link, vendor, renewal, remove);
  if (payload.low_confidence) {
    const warning = document.createElement("span");
    warning.className = "upload-partial";
    warning.textContent = LOW_CONFIDENCE_LABEL;
    warning.title = LOW_CONFIDENCE_TITLE;
    li.append(warning);
  }
  list.appendChild(li);
  wireRemove(remove);
}
```

This is the *only* asymmetric point in the upload list's lifecycle: removing
a row already fades + slides it out first (see `removeRow()` a few lines
above `addRow()`, and `.upload-list li.is-removing` in
`app/static/css/theme.css:1488`), but adding one just teleports it in. The
CSS transition that would drive an entrance is already declared on the base
`li` rule and sitting unused for this purpose:

```css
/* app/static/css/theme.css:1475-1484 — current */
.upload-list li {
  display: grid;
  grid-template-columns: 5.5rem 1fr auto auto;
  gap: 0.75rem;
  align-items: center;
  padding: 10px 0;
  border-top: 1px solid var(--border);
  font-size: var(--text-base);
  transition: opacity var(--duration-base) var(--ease-out), transform var(--duration-base) var(--ease-out);
}
/* Removing an upload used to just vanish the row. Class is toggled in
   app.js's wireRemove() right before the row is actually taken out of the
   DOM, so the fade-and-slide plays first. */
.upload-list li.is-removing { opacity: 0; transform: translateX(-8px); }
.upload-list li:first-child { border-top: none; }
```

## Target

`addRow()` sets the new `li`'s inline style to the same end-state values
`.is-removing` already uses (`opacity: 0`, `translateX(-8px)`) *before*
appending it, appends it, forces a reflow, then clears the inline style so
the element transitions to its natural resting state under the
already-declared `transition: opacity var(--duration-base) var(--ease-out), transform var(--duration-base) var(--ease-out)`.
No new CSS is required — the existing rule already covers both directions
once the JS drives the starting state.

```js
/* target: app/static/js/app.js addRow(), around what is currently line 381 */
const li = document.createElement("li");
li.dataset.contractId = payload.contract_id;
li.style.opacity = "0";
li.style.transform = "translateX(-8px)";
// ...(link/vendor/renewal/remove/warning construction unchanged)...
list.appendChild(li);
// Force a reflow so the browser commits the starting style before the
// transition target is applied - without this the two writes coalesce
// into one frame and the row never visibly animates in.
li.offsetHeight;
li.style.opacity = "";
li.style.transform = "";
wireRemove(remove);
```

## Repo conventions to follow

- Motion tokens live in `app/static/css/theme.css:79-80`:
  `--duration-base: 200ms;` and (from `theme.css:77`) `--ease-out: cubic-bezier(0.16, 1, 0.3, 1);`.
  This plan introduces no new tokens — it reuses the transition already
  declared on `.upload-list li` (`theme.css:1483`).
- Exemplar for the "force a reflow to restart a CSS transition from an
  inline starting style" pattern: none exists yet in this repo for *entry*,
  but the *exit* half of the exact same symmetric pair is
  `app/static/js/app.js` `removeRow()` (the function immediately above
  `addRow()`), which toggles `.is-removing` and lets the CSS class drive the
  transition declaratively. This plan keeps the same declarative CSS-first
  approach — inline styles are used only because the entrance needs a
  *specific instance's* starting state, not a reusable named state.

## Steps

1. Open `app/static/js/app.js`. Locate `addRow()` (starts at line 368).
2. Immediately after `const li = document.createElement("li");` (line 381)
   and before `li.dataset.contractId = payload.contract_id;` (line 382), add:
   ```js
   li.style.opacity = "0";
   li.style.transform = "translateX(-8px)";
   ```
3. Leave every line between the current 382 and 408 (`list.appendChild(li);`)
   unchanged — all the child-element construction and the `low_confidence`
   branch stay exactly as they are.
4. Immediately after `list.appendChild(li);` (currently line 408) and before
   `wireRemove(remove);` (currently line 409), add:
   ```js
   li.offsetHeight;
   li.style.opacity = "";
   li.style.transform = "";
   ```
5. Do not touch `app/static/css/theme.css` — the existing `.upload-list li`
   transition (line 1483) and `.is-removing` rule (line 1488) are sufficient
   and must not be duplicated or modified.

## Boundaries

- Do NOT touch `removeRow()`, `wireRemove()`, or any other function in
  `app/static/js/app.js`.
- Do NOT touch `app/static/css/theme.css`.
- Do NOT change the DOM structure of the `<li>` (element order, classes,
  attributes) — only the three inline-style lines described above.
- Do NOT add a CSS class (e.g. `.is-entering`) — the inline-style approach
  is deliberate here because each row's starting transform must be set
  synchronously before paint, and doing that via a class would need the
  same two-write-plus-reflow dance anyway with more code.
- If `addRow()` no longer matches this excerpt (line numbers or structure
  have drifted since commit `f3e9862`), STOP and report instead of guessing
  where to insert the three lines.

## Verification

- **Mechanical**: no build step for this repo (Jinja + vanilla JS/CSS served
  directly by FastAPI). Confirm the file is still valid JS by running
  `node --check app/static/js/app.js` and expect no output (exit code 0).
- **Feel check**:
  1. Start the dev server (`.venv/bin/uvicorn app.main:app --reload --port 8420`
     or the `pact-dev` launch config) and open `/`.
  2. Enable Demo Mode (sidenav toggle) so extraction finishes near-instantly.
  3. Upload `docs/demo-assets/sample-contract.txt` via "Choose a file".
  4. Confirm the new row fades and slides in from the left (from
     `translateX(-8px)` to its resting position) rather than appearing
     instantly — visually the mirror image of removing a row.
  5. In Chrome DevTools' Animations panel, set playback to 10% and confirm
     the entrance and an exit (click "Remove" on any row) look like the same
     motion played in reverse — same duration, same easing curve.
  6. Toggle `prefers-reduced-motion` (Rendering panel). Confirm the row still
     appears (opacity still resolves to 1) — this repo's existing reduced-motion
     block (`theme.css` `@media (prefers-reduced-motion: reduce)`) already
     sets `.upload-list li { transition: none; }`, so the row will appear
     instantly with no residual transform stuck at `translateX(-8px)`. Verify
     specifically that it does NOT get stuck invisible or offset.
  7. Upload two files in quick succession and confirm both rows animate in
     independently with no visual glitch (each `li` has its own inline
     style, so there is no shared state to collide).
- **Done when**: a freshly uploaded row visibly fades+slides in from the same
  offset (`translateX(-8px)`, `opacity 0→1`) that a removed row fades+slides
  out to, using the existing `--duration-base`/`--ease-out` tokens, with no
  new CSS added and no regression under reduced motion.
