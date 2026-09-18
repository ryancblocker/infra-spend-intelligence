# 002 — Add missing hover transitions to feed-row and row-link

- **Status**: TODO
- **Commit**: f3e9862
- **Severity**: LOW
- **Category**: Cohesion & tokens / Easing & duration
- **Estimated scope**: 1 file (`app/static/css/theme.css`), 2 rules

## Problem

Two clickable-text hover states in `app/static/css/theme.css` change color
with no `transition` at all, so the color hard-cuts on hover instead of
easing like every comparable hover state elsewhere in the file:

```css
/* app/static/css/theme.css:749-750 — current */
tbody a.row-link { text-decoration: none; font-weight: 700; color: var(--ink-primary); }
tbody a.row-link:hover { color: var(--brand-text); }
```

```css
/* app/static/css/theme.css:1039-1040 — current */
a.feed-row:hover .feed-title { color: var(--brand-text); }
.feed-title { font-weight: 700; font-size: var(--text-base); }
```

`.row-link` is used for every contract/run ID link in every table
(`app/templates/contracts.html:34`, `findings.html:57`,
`run_detail.html:9`, `runs.html:29`). `.feed-title` is the link text inside
every `a.feed-row` (`mission_control.html:262-268` "Top Savings
Opportunities" and "Upcoming Renewals", `contract_detail.html` feed rows).
Both are hit tens of times a day by anyone scanning these dashboard lists.

Every other comparable hover in this file already transitions its color —
e.g. `.nav-link`:

```css
/* app/static/css/theme.css:488-501 — exemplar, already correct */
.nav-link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  color: var(--ink-secondary);
  text-decoration: none;
  font-size: var(--text-base);
  font-weight: 600;
  transition: background var(--duration-fast) var(--ease-out), color var(--duration-fast) var(--ease-out);
}

.nav-link:hover { background: var(--surface-2); color: var(--ink-primary); }
```

`.row-link` and `.feed-title` are the two outliers.

## Target

```css
/* target: app/static/css/theme.css:749-750 */
tbody a.row-link {
  text-decoration: none;
  font-weight: 700;
  color: var(--ink-primary);
  transition: color var(--duration-fast) var(--ease-out);
}
tbody a.row-link:hover { color: var(--brand-text); }
```

```css
/* target: app/static/css/theme.css:1039-1040 */
.feed-title {
  font-weight: 700;
  font-size: var(--text-base);
  transition: color var(--duration-fast) var(--ease-out);
}
a.feed-row:hover .feed-title { color: var(--brand-text); }
```
(Reordered so the base `.feed-title` rule, which now carries the
`transition`, appears before the `:hover` rule that overrides `color` — pure
readability, source order doesn't affect the cascade here since they target
different states of the same property.)

## Repo conventions to follow

- Motion tokens live in `app/static/css/theme.css:79`:
  `--duration-fast: 120ms;` and `theme.css:77`:
  `--ease-out: cubic-bezier(0.16, 1, 0.3, 1);`. This plan introduces no new
  tokens — it applies the exact `--duration-fast`/`--ease-out` pair
  `.nav-link` already uses for its hover color transition.
- Exemplar: `.nav-link` at `theme.css:488-501` (quoted above under Problem).
  Follow its exact pattern — `transition: color var(--duration-fast) var(--ease-out);`
  on the base rule, the `:hover` rule only sets the target `color`.

## Steps

1. Open `app/static/css/theme.css`. Locate the `tbody a.row-link` rule
   (line 749).
2. Add `transition: color var(--duration-fast) var(--ease-out);` as a new
   declaration inside that rule (order within the rule doesn't matter;
   append it after `color: var(--ink-primary);` for readability). Leave
   `tbody a.row-link:hover` (line 750) unchanged.
3. Locate the `.feed-title` rule (line 1040, currently
   `.feed-title { font-weight: 700; font-size: var(--text-base); }`).
4. Add `transition: color var(--duration-fast) var(--ease-out);` as a new
   declaration inside that rule. Leave `a.feed-row:hover .feed-title`
   (line 1039) unchanged.

## Boundaries

- Do NOT touch any other selector in `theme.css`.
- Do NOT touch any template file — this is CSS-only.
- Do NOT change `--duration-fast` or `--ease-out` themselves, and do NOT
  introduce a new token — reuse the existing pair exactly as named.
- If the current content of either rule (quoted in Problem/Target above) has
  drifted from what's in the file, STOP and report instead of guessing
  where the properties live now.

## Verification

- **Mechanical**: no build step for this repo. Confirm the file still parses
  as valid CSS — e.g. `python3 -c "s=open('app/static/css/theme.css').read(); assert s.count('{')==s.count('}')"`
  and expect no `AssertionError`.
- **Feel check**:
  1. Start the dev server and open `/` (Mission Control) — hover over a row
     under "Top Savings Opportunities" or "Upcoming Renewals" and confirm
     the title text eases from `--ink-primary` to `--brand-text` over
     roughly 120ms instead of snapping instantly.
  2. Open `/contracts` and hover a contract ID in the table — confirm the
     same eased color change.
  3. In Chrome DevTools' Animations panel, set playback to 10% while
     hovering and confirm a visible, smooth color ramp rather than a single
     jump-cut frame.
  4. Toggle `prefers-reduced-motion` (Rendering panel) and confirm the hover
     color change still happens (this is a color transition, not a movement
     transition, so it is intentionally left running even under reduced
     motion — do not add a reduced-motion override for it).
- **Done when**: both `.row-link` (in tables) and `.feed-title` (inside
  `a.feed-row`) ease their hover color over `--duration-fast` with
  `--ease-out`, matching `.nav-link`'s existing hover treatment exactly, and
  no other rule in the file changed.
