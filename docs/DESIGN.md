# Docket — Design System & Redesign Brief

Docket is a civic-intelligence answer engine + analytics dashboard over ~14,338 Philadelphia
City Council bills (2012–2026). This spec synthesizes the team research into ONE restrained,
credible, dark-theme design system in the Linear / Vercel / Stripe / Perplexity register, and
gives a per-file redesign brief.

## HARD CONSTRAINT FOR IMPLEMENTERS

Do **NOT** change any data fetching, state, hooks, `useEffect`, API calls, event handlers, or
logic. Change **only the returned JSX structure and `className`s**, plus additive CSS in
`globals.css`. Every brief below is written against the data each page already has. If a brief
implies data that isn't fetched, skip that part — never add a fetch.

---

## 1. Design principles (the whole product, in one voice)

1. **One accent, doing all the work.** `--accent` (#6c8cff) means "interactive / live data"
   and nothing else. Never use it for decorative headers, borders, or dividers. Reserve
   `--ok` green for affirmative/enacted state, `--danger` red for genuine API errors and
   dissent votes only. A refusal is **never** red.
2. **Whitespace is the credibility signal.** Big gaps *between* sections (32–48px), tight
   uniform rhythm *within* a list (8–12px). Prefer labeled sections + hairlines over
   boxes-in-boxes. Stop nesting bordered panels.
3. **Two content widths.** Prose/answer surfaces stay at ~720px (`--measure-prose`). Data
   surfaces (analytics, browse, compare) widen to ~1080px (`--measure-wide`) so charts and
   rows breathe.
4. **Every number is tabular.** `font-variant-numeric: tabular-nums` on all counts, dates,
   tallies, stat values so columns align and read as auditable data.
5. **Lead with the product working.** On home, the ask box is the hero, not scrolled-to
   furniture. Personal/dashboard modules (Watchlist, Digest, Insights) live below the fold.
6. **Trust is a layout property.** Answer + citations are one visually-bound unit. Refusals
   read as deliberate, calm honesty. Every fact stays one hop from its Legistar source.
7. **Three distinct "no content" meanings, three looks:** empty-by-design (warm, one action),
   zero-results (neutral, offer to loosen), error (muted-red, retry). Never one grey `.note`
   for all three.
8. **Calm, fast motion only.** 120–160ms color/background transitions on hover/focus; keep the
   existing `prefers-reduced-motion` discipline. No entrance animations, carousels, or a
   second accent.

---

## 2. Token additions (globals.css `:root`)

Keep every existing token. Add a small, disciplined set — no new colors except one success-
adjacent already present (`--ok`) and a soft success wash:

```css
:root {
  /* content widths */
  --measure-prose: 720px;   /* ask/answer, about, account */
  --measure-wide: 1080px;   /* analytics, browse, compare */

  /* 4px spacing scale (reference these instead of raw px going forward) */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --space-8: 48px;

  /* status wash (dual-encoded with text, never color-only) */
  --ok-soft: rgba(87, 217, 163, 0.13);
  --danger-soft: rgba(255, 123, 123, 0.12);
  --muted-soft: rgba(139, 148, 166, 0.12);
}
```

Add a wide-container helper (do not change `.container`, which stays 720px):

```css
.container-wide { max-width: var(--measure-wide); margin: 0 auto; padding: 48px 24px 96px; }
@media (max-width: 640px) { .container-wide { padding: 28px 16px 64px; } }
```

---

## 3. Component library (named classes + intended CSS)

All CSS below is **additive** to `globals.css` and uses existing tokens. Existing classes
(`.panel`, `.bill-row`, `.stat`, `.bars`, `.citations`, `.sponsor-list`, etc.) are kept and,
where noted, tightened.

### `.page-header` — universal page identity block
Breadcrumb → H1 → meta line → optional actions. Closed by a hairline so the eye registers
"where am I" before content.
```css
.page-header { margin-bottom: var(--space-6); padding-bottom: var(--space-5);
  border-bottom: 1px solid var(--border); }
.page-header .eyebrow { margin-bottom: 10px; }
.page-header h1 { margin-bottom: 8px; }
.page-header-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px;
  color: var(--muted); font-size: 0.9rem; font-variant-numeric: tabular-nums; }
.page-header-actions { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
```

### `.breadcrumb` — chevron-separated context trail
Replaces the ad-hoc "Docket · Browse · Ask" eyebrow lines. Last crumb is current (not a link).
```css
.breadcrumb { display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
  font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--muted); font-weight: 600; margin: 0 0 4px; }
.breadcrumb a { color: var(--muted); }
.breadcrumb a:hover { color: var(--text); }
.breadcrumb .sep { opacity: 0.5; }
.breadcrumb .current { color: var(--accent); }
```

### `.hero` / `.hero-input` / `.hero-stats` — home answer-box hero
Centered, breathing, headline-forward. The ask input is the biggest interactive target.
```css
.hero { padding-top: var(--space-6); margin-bottom: var(--space-8); }
.hero h1 { font-size: 2.9rem; letter-spacing: -0.03em; margin-bottom: 14px; }
.hero .lede { font-size: 1.12rem; margin-bottom: var(--space-6); }
/* the ask textarea styled as one confident search bar */
.hero-input textarea { font-size: 1.05rem; padding: 16px 18px; min-height: 60px;
  border-radius: var(--radius-lg); }
.hero-stats { display: flex; flex-wrap: wrap; gap: 8px 40px; margin: 0 0 var(--space-6); }
.hero-stat { display: flex; flex-direction: column; gap: 2px; }
.hero-stat-num { font-size: 1.75rem; font-weight: 700; color: var(--text);
  font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }
.hero-stat-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.1em;
  color: var(--muted); }
@media (max-width: 640px) { .hero h1 { font-size: 1.75rem; } .hero-stats { gap: 14px 28px; } }
```

### `.kpi-grid` / `.kpi` — analytics stat tiles (replaces `.stats` inside a `.panel`)
4-tile responsive grid; big tabular value, small caps label, optional context line. Hairline
card with hover lift; clickable variant `.kpi-link`.
```css
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-4); margin-bottom: var(--space-6); }
.kpi { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 16px 18px; display: flex; flex-direction: column; gap: 6px; }
.kpi-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); }
.kpi-num { font-size: 1.9rem; font-weight: 700; color: var(--text);
  font-variant-numeric: tabular-nums; letter-spacing: -0.01em; line-height: 1.1; }
.kpi-context { font-size: 0.8rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.kpi-link { transition: border-color 0.15s var(--ease), background 0.15s var(--ease); }
.kpi-link:hover { border-color: var(--border-hover); background: var(--panel-2);
  text-decoration: none; }
```

### `.section-head` — insight-first section title (upgrade of `.section-title`)
A plain-English takeaway line, then a muted context line. Keep `.section-title` for label-only
uses; use `.section-head` where a chart/list needs a caption.
```css
.section-head { margin: 0 0 var(--space-4); }
.section-head-title { font-size: 1rem; font-weight: 600; color: var(--text); margin: 0 0 2px; }
.section-head-caption { font-size: 0.8rem; color: var(--muted);
  font-variant-numeric: tabular-nums; margin: 0; }
```

### `.chart-frame` — uniform chart container row inside a panel
Just enforces consistent spacing between a section head and its bars/sparkline; no border.
```css
.chart-frame { margin-top: var(--space-2); }
```

### `.data-list` / `.data-row` — single-surface list (retires card-per-row for browse/topic)
One bordered panel, hairline dividers, fixed row rhythm, hover = background lift (not border
flip). This is THE row primitive; `.bill-row` is refactored to sit inside it.
```css
.data-list { border: 1px solid var(--border); border-radius: var(--radius-lg);
  background: var(--panel); overflow: hidden; }
.data-row { display: grid; grid-template-columns: 1fr auto; align-items: baseline;
  gap: 4px 16px; padding: 11px 16px; border-bottom: 1px solid var(--border);
  color: var(--text); transition: background 0.12s var(--ease); }
.data-row:last-child { border-bottom: none; }
.data-row:hover { background: var(--panel-2); text-decoration: none; }
.data-row-title { font-size: 0.94rem; overflow-wrap: anywhere; }
.data-row-meta { font-size: 0.8rem; color: var(--muted); text-align: right; white-space: nowrap;
  font-variant-numeric: tabular-nums; }
@media (max-width: 640px) {
  .data-row { grid-template-columns: 1fr; }
  .data-row-meta { text-align: left; white-space: normal; }
}
```
> Refactor the existing `.bill-row` to drop its own border/margin/radius and instead reuse
> `.data-row` inside a `.data-list` wrapper. (Keep the class name working by aliasing: give
> `.bill-row` the same rules as `.data-row` if it's easier than renaming call sites — see
> per-file briefs. Both approaches are fine; do NOT leave card-per-row.)

### `.status-token` — small colored state pill (dual-encoded, never color-only)
For bill status in rows and headers. Text always present; color/border reinforces.
```css
.status-token { display: inline-block; padding: 1px 9px; border-radius: 999px;
  font-size: 0.7rem; font-weight: 600; letter-spacing: 0.03em; text-transform: uppercase;
  border: 1px solid var(--border); color: var(--muted); background: var(--muted-soft);
  vertical-align: middle; white-space: nowrap; }
.status-token.is-ok { color: var(--ok); border-color: rgba(87,217,163,0.35); background: var(--ok-soft); }
.status-token.is-danger { color: var(--danger); border-color: rgba(255,123,123,0.35); background: var(--danger-soft); }
```
> Mapping (implementers apply with a tiny inline map, no new fetch): ENACTED / ADOPTED →
> `is-ok`; FAILED / VETOED / PLACED ON FILE → `is-danger`; everything else (IN COMMITTEE,
> INTRODUCED) → default muted.

### `.entity-header` / `.stat-chips` / `.chip-stat` — bill/member/topic identity block
Extends `.page-header` with a row of compact stat chips (big number + small label).
```css
.stat-chips { display: flex; flex-wrap: wrap; gap: 20px 28px; margin-top: 14px; }
.chip-stat { display: flex; flex-direction: column; gap: 1px; }
.chip-stat-num { font-size: 1.25rem; font-weight: 700; color: var(--text);
  font-variant-numeric: tabular-nums; }
.chip-stat-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); }
```

### `.detail-grid` / `.detail-main` / `.detail-side` — content + sticky metadata sidebar
Wide primary column + narrow sticky facts rail; collapses to one column under 1024px.
```css
.detail-grid { display: grid; grid-template-columns: minmax(0,1fr) 320px; gap: var(--space-5);
  align-items: start; }
.detail-side { position: sticky; top: 84px; display: flex; flex-direction: column;
  gap: var(--space-5); }
@media (max-width: 1024px) {
  .detail-grid { grid-template-columns: 1fr; }
  .detail-side { position: static; }
}
```

### `.meta-list` — definition-list metadata (replaces comma-joined `.note` header lines)
Precise key→value rows in the sidebar.
```css
.meta-list { display: grid; grid-template-columns: auto 1fr; gap: 8px 16px; margin: 0; }
.meta-list dt { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--muted); align-self: baseline; }
.meta-list dd { margin: 0; font-size: 0.9rem; color: var(--text); text-align: right;
  overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.meta-list dd.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--accent); }
```

### `.timeline-rail` — vertical timeline with connector (restyle of `.timeline-list`)
A left rail with a dot per event; current/terminal status emphasized. Additive; the existing
`.timeline-list` grid is kept for the inline citation-expand view, this is for the bill page.
```css
.timeline-rail { list-style: none; margin: 0; padding: 0 0 0 18px; position: relative;
  border-left: 2px solid var(--border); }
.timeline-rail li { position: relative; display: grid; grid-template-columns: 96px 1fr;
  gap: 12px; padding: 0 0 14px; font-size: 0.85rem; }
.timeline-rail li::before { content: ""; position: absolute; left: -25px; top: 5px;
  width: 8px; height: 8px; border-radius: 50%; background: var(--border);
  box-shadow: 0 0 0 3px var(--bg); }
.timeline-rail li:first-child::before { background: var(--accent); }
.timeline-rail li:first-child .tl-action { color: var(--text); font-weight: 600; }
.timeline-rail .tl-date { color: var(--muted); font-variant-numeric: tabular-nums; }
```
> Newest-first ordering makes "where is this bill now" the emphasized first node. NOTE: the
> bill page currently renders timeline in source order (oldest-first, `<ol>`). Do NOT reorder
> the data. Instead emphasize the LAST node as current by adding a `is-current` class to the
> final `<li>` and styling it; keep `:first-child` accent rule only if you also flip to
> newest-first, which requires a logic change — so **prefer the `.is-current` on last child**:
```css
.timeline-rail li.is-current::before { background: var(--accent); }
.timeline-rail li.is-current .tl-action { color: var(--text); font-weight: 600; }
```

### `.vote-tally` — roll-call as a segmented bar + dissent chips
Yea/Nay/Abstain proportions with counts labeled; dual-encoded (position + text, not color
alone). Dissenters are clickable member chips.
```css
.vote-tally { margin: 8px 0 0; }
.vote-bar { display: flex; height: 12px; border-radius: 999px; overflow: hidden;
  border: 1px solid var(--border); background: var(--bg); }
.vote-seg { height: 100%; }
.vote-seg.yea { background: var(--ok); }
.vote-seg.nay { background: var(--danger); }
.vote-seg.abstain { background: var(--muted); }
.vote-legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 8px;
  font-size: 0.8rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.vote-dissent { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.member-chip { display: inline-flex; align-items: baseline; gap: 4px; padding: 3px 10px;
  border-radius: 999px; border: 1px solid var(--border); background: var(--panel-2);
  font-size: 0.8rem; }
.member-chip:hover { border-color: var(--border-hover); text-decoration: none; }
```
> Roll-call data only reliably has a `tally` map (e.g. Ayes/Nays) and a `votes` list. Build the
> segments from `tally` keys that exist; the dissent list already exists in code. Do not invent
> abstain if it isn't in the tally.

### `.source-card` / `.source-grid` — answer citation strip (Perplexity model)
Numbered source cards immediately under the answer, bound in the same response block. This is a
CSS layer on top of the existing `CitationList` (which already expands timelines inline — keep
that). Use for the ask-answer sources region.
```css
.response { background: var(--panel); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 24px; box-shadow: var(--shadow); }
.response .answer { margin-bottom: 0; }
.source-divider { display: flex; align-items: center; gap: 10px; margin: 20px 0 12px;
  font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); }
.source-divider::after { content: ""; flex: 1; height: 1px; background: var(--border); }
```

### `.grounding-pill` — evidence-strength signal on an answer
"Grounded in N bills" with a calibrated, dual-encoded label. Derive from citation count only
(no new fetch): 0 → refusal path; 1–2 → "Limited record" (muted); 3+ → "Well supported" (ok).
```css
.grounding-pill { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px;
  border-radius: 999px; font-size: 0.75rem; font-weight: 600; border: 1px solid var(--border);
  color: var(--muted); background: var(--muted-soft); font-variant-numeric: tabular-nums; }
.grounding-pill.is-strong { color: var(--ok); border-color: rgba(87,217,163,0.35); background: var(--ok-soft); }
```

### `.refusal-card` — refusal as a first-class calm state (upgrade of `.refusal`)
Keep the left-border, add a calm eyebrow and reroute chips. Never red.
```css
.refusal-card { border-left: 3px solid var(--border); padding: 4px 0 4px 16px; }
.refusal-eyebrow { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.1em;
  color: var(--muted); font-weight: 600; margin: 0 0 6px; }
.refusal-card .answer { color: var(--muted); margin-bottom: 12px; }
.refusal-actions { display: flex; flex-wrap: wrap; gap: 8px; }
```
> Reroute chips reuse `.example-chip` styling. Wire them to existing setters only (e.g. an
> example question, or a `<Link href="/browse">`). No new state.

### `.empty-state` / `.error-state` — the three no-content variants
```css
.empty-state { text-align: center; padding: 44px 24px; }
.empty-state-title { font-size: 0.98rem; color: var(--text); margin: 0 0 6px; }
.empty-state-help { font-size: 0.85rem; color: var(--muted); margin: 0 0 16px; }
.empty-state-actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.error-state { border-left: 3px solid var(--danger); background: var(--danger-soft);
  border-radius: var(--radius); padding: 14px 16px; }
.error-state-msg { color: var(--danger); font-size: 0.9rem; margin: 0 0 10px; }
```
> `.empty-state` variant='empty' gets a primary action; variant='no-results' gets a
> "loosen/clear" action. `.error-state` gets a Retry that re-runs the SAME handler the page
> already has. Where a component currently `return null`s on failure, prefer an inline
> `.error-state` in its footprint — but ONLY if a retry handler already exists; otherwise leave
> the existing degrade-to-hidden logic untouched (no new logic).

### `.toolbar` — persistent scope/filter bar (analytics, browse)
Slim, chrome-not-data. Title/eyebrow left, controls right; filters echo as removable chips.
```css
.toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: var(--space-5); }
.toolbar-controls { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 12px; }
.filter-chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 var(--space-4); }
```
> Filter chips reuse `.example-chip`. A removable chip shows `Status: ENACTED ×`. Wire the ×
> to the existing setter (`setStatus("")`, etc.) — this is JSX + existing setters only, no new
> state. Only add chips where the state already exists (browse: q/status/jurisdiction).

### Tightened existing classes
- `.stat-num`: bump to a headline weight where used as a KPI — but prefer migrating those call
  sites to `.kpi`. Add `font-variant-numeric: tabular-nums;` to `.stat-num`.
- `.bar-value`, `.sponsor-count`, `.trend-total`, `.coverage-jz-count`: already tabular — keep.
- `.sponsor-list li`: give the value column `font-variant-numeric: tabular-nums` (via
  `.sponsor-count`, already present) and consider promoting "Most active sponsors" to a
  length-encoded bar list reusing `.bars` for visual ranking (optional, see analytics brief).
- `.example-chip`: reused as filter chips, reroute chips, quick-add chips — one vocabulary.
- Sparkline endpoint: in `Trends.tsx`/`Sparkline`, add a `<circle>` at the last point in
  `var(--accent)` and an `aria-label` summarizing first→last (SVG markup only, no logic).

---

## 4. Per-file redesign briefs

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/globals.css`
Add the tokens (§2) and every component class (§3). Tighten `.bill-row` → `.data-row`
semantics. Add `.container-wide`. Add `tabular-nums` to `.stat-num`. Do not remove existing
classes; other components still reference them.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/page.tsx` (Home)
**Reorder for answer-box-as-hero.** New top-to-bottom order of the returned JSX (all existing
state/handlers unchanged):
1. `.hero`: keep eyebrow "Docket"; **rewrite h1** from the task label to a value assertion —
   e.g. "Answers about Philadelphia legislation you can actually cite." Keep the existing lede
   verbatim.
2. `.hero-stats` row (4 quiet stats). Use values already available at render: the ask page does
   NOT fetch overview, but it DOES fetch `jurisdictions`. Safe stats without new fetches:
   total documents = sum of `jurisdictions[].documents` (already in state), "2012–2026
   coverage" (static copy consistent with the corpus), jurisdiction count, and "Every answer
   cited" as the trust stat. Only render the numeric stats when `jurisdictions.length` is set;
   otherwise show the static ones. No new fetch.
3. The **ask box as hero**: move the current "Ask a question" `.panel` (the jurisdiction
   select + `.examples` + form) directly under the stats. **Delete** the redundant
   `.home-section-title "Ask a question"` + `.home-section-sub` — the h1/lede already frame it.
   Style the textarea via `.hero-input` (single confident bar; keep `rows={4}` prop, CSS makes
   it read as a search bar). Keep the example chips. Add a secondary ghost CTA "Browse all
   bills" (`Link` to `/browse`, `.btn-secondary`) in the `.row` beside "Ask Docket".
4. The streaming/answer/error blocks stay **immediately** below the input (they already do).
   Wrap the answer + citations in `.response`. For the answer:
   - Add a `.grounding-pill` at the top of a non-refused answer: "Grounded in N bills" where N
     = `result.citations.length`; `is-strong` when N ≥ 3. (Derived from existing data.)
   - Replace the "Citations —" `.section-title` with a `.source-divider` reading "SOURCES".
     Keep `<CitationList>` exactly as-is below it.
   - Refusal branch: render as `.refusal-card` with a `.refusal-eyebrow` "No grounded answer",
     the `result.answer`, and `.refusal-actions` reroute chips (`.example-chip`): one that
     repopulates an EXAMPLE via `setQuestion`, one `Link` to `/browse`. Never `status-err`.
   - The network `error` note stays as `status-err` (this is the true error path) — keep it
     visually distinct from the refusal so users learn red = broke, bordered-calm = honest.
5. **Below the fold**, in this order: `Digest` (public freshness), `InsightsPanel`, then
   `Watchlist` LAST (personal, empty for logged-out). Remove the "Your watchlist" /
   "This week's digest" `.home-section-title` + sub wrappers or keep them but demote below the
   ask; do NOT let Watchlist open the page. Each keeps its own component chrome.

Improvements: hierarchy (promise → live demo → proof → dashboard), whitespace in hero,
credibility via grounding pill + bound sources.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/analytics/page.tsx`
**Widen and restructure into a real dashboard.** Change `.container` → `.container-wide` on the
`<main>`s (loading, failed, and view). Keep all fetches/state.
1. `.page-header`: `.breadcrumb` (Docket › Analytics), h1 "Analytics" (keep the
   `· jurisdiction` suffix from existing state), meta line = the existing whole-corpus
   description. Optionally a `.toolbar` under it — but the only real control that exists is the
   URL `jurisdiction`; do NOT invent a range control (no such state). If you want the scope
   visible, echo it as a single read-only `.filter-chips` chip when `jurisdiction` is set.
2. Replace the `.panel > .stats` KPI block with a `.kpi-grid` of `.kpi` tiles built from the
   SAME data: total_documents, avg_days_to_enact, enacted, intro-date span. Make the
   total_documents and enacted tiles `.kpi-link` wrapped in a `Link` to a filtered `/browse`
   (e.g. `/browse` and `/browse?status=ENACTED`) — routes that already exist. Span tile stays a
   plain `.kpi` (no delta — deltas on a range are nonsense; the research is explicit).
3. Monthly volume: wrap the section title in `.section-head` — takeaway line "Introduction
   volume, last N months" + caption "newest last · current month partial" (the "partial" note
   is honest and matches the research; only add if factually safe — it is, the trailing month
   is always incomplete). Keep the existing `.bars` render (horizontal bars are fine and
   already good). Do not add a chart library.
4. Put "Status breakdown" and "Document types" **side by side** in a two-column grid instead of
   two stacked full-width panels (they are comparisons). Add:
   ```css
   .breakdown-2 { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-4); }
   @media (max-width: 720px) { .breakdown-2 { grid-template-columns: 1fr; } }
   ```
   Each still uses `BarBreakdown`/`.bars`. Add `is-ok`/`is-danger` semantics to status bars is
   optional; if done, keep it dual-encoded (the label text is already present).
5. "Most active sponsors": promote to a length-encoded bar list for visual ranking — reuse
   `.bars`/`.bar-row` with the sponsor name as `.bar-label` (wrapped in the existing `Link`)
   and `s.bills` as `.bar-value`; compute max from `sponsors` (render-time only, no new state).
   This unifies the visual language. Keep the fallback plain list if simpler.
6. Skeleton: the generic `PanelSkeleton lines={6}` causes a reflow. Optionally compose a
   KPI-row + bars-shaped skeleton, but this is JSX-only and must not touch the loading logic —
   safe to add a shaped fallback that renders `.kpi-grid` of `.skeleton` blocks. Keep the
   existing `.eyebrow` label.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/browse/page.tsx`
**Single-surface list + visible filters + honest count.** Change `.container` →
`.container-wide`. Keep all state/handlers/CSV/pagination logic.
1. `.page-header`: breadcrumb (Docket › Browse), keep h1 and lede.
2. Keep the filter `.panel`/`.browse-filters` form as-is (top-mounted is right). Below the
   `</form>`, add `.filter-chips` that echo active filters as removable `.example-chip`s:
   `Title: "{q}" ×`, `Status: {status} ×`, `City: {jurisdiction} ×`. Each × calls the existing
   setter (`setQ("")`, `setStatus("")`, `setJurisdiction("")`) — existing state only, no new
   hooks. Render a chip only when its value is set.
3. Results: replace the card-per-row `.bill-row` loop with a `.data-list` wrapper containing
   `.data-row` links. Row layout: title line = `#{file_no} · {title}` as `.data-row-title`;
   right column `.data-row-meta` = `{doc_type} · {intro_date}` with the **status rendered as a
   `.status-token`** (dual-encoded). Keep the `href` and `key` exactly.
4. The "N matching bills — showing X-Y of N" count line stays (`.note`); keep tabular. Keep
   Prev/Next and Export exactly. For the empty result, swap the flat "No bills match these
   filters." for an `.empty-state` variant='no-results' with a "Clear filters" action wired to
   the existing setters (calls `setQ("")`/`setStatus("")`/`setJurisdiction("")` then nothing
   else — no auto-refetch added). Network error stays `.error-state` (or keep `status-err`).
Improvements: scan speed (one list, hairlines), visible filter state, color-scannable status.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/compare/page.tsx`
**Widen + header + consistent columns.** Change `.container` → `.container-wide`. Keep all
state/URL logic.
1. `.page-header`: breadcrumb (Docket › Compare), keep h1 and lede.
2. Keep `.compare-picker`/`.browse-filters` selects. Keep `.compare-grid` two-column (already
   collapses on mobile).
3. In `CompareColumn`, replace stacked `.section-title`s with `.section-head` where a caption
   helps (the sparkline's year range). Render the count with `.chip-stat` styling for a
   headline number. Sponsors list: keep `.sponsor-list`; ensure `.sponsor-count` tabular
   (already is). Add the sparkline endpoint dot (see Trends brief) — since compare imports
   `Sparkline` from Trends, the improvement flows automatically once Trends is updated.
4. Empty "Pick two topics" → `.empty-state` variant='empty'. Failure branch → keep or upgrade
   to `.error-state` (no retry handler exists cleanly, so keeping the existing note is
   acceptable — do not add logic).

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/bill/[file_no]/page.tsx`
**Identity header + two-column detail + rail timeline + vote tally.** Keep `.container`
(720px is fine, but the two-col grid benefits from width — use `.container-wide`). Keep every
fetch/state.
1. `.entity-header` (built on `.page-header`): breadcrumb (Docket › Bill › `#{fileNo}`), h1 =
   `timeline?.title ?? #{fileNo}`, then `.page-header-meta` with a `.status-token` for
   `timeline.status` (dual-encoded via the map) and the Legistar link as an action. Replace the
   comma-joined `.note` line entirely.
2. `.detail-grid`: 
   - `.detail-main`: the **Timeline** panel using `.timeline-rail` (restyle the existing
     `<ol className="timeline-list">` → `.timeline-rail`; add `.is-current` to the LAST `<li>`
     — a render-time index check, no data reorder). Then the **Roll-call** section using
     `.vote-tally`: build `.vote-seg`s from `rollcall.tally` entries (map Ayes→yea, Nays→nay,
     else→abstain by key name at render time), the `.vote-legend` from the same tally, and the
     existing `dissent` array as `.member-chip` links (dissenters already computed). Keep the
     "No roll-call recorded" note as a calm inset when absent.
   - `.detail-side` (sticky): a `.meta-list` `<dl>` of the facts already on the page — File no
     (`.mono`), Status, Legistar (link) — plus the Sponsors list (move the existing Sponsors
     `.sponsor-list` here) and the "More from this sponsor" `.data-list` (convert those
     `.bill-row`s to `.data-row`). Sidebar collapses below on mobile.
3. Not-found and loading states keep their logic; give not-found an `.empty-state`.
Improvements: scannable identity, sticky facts, timeline answers "where is it now", vote is a
glance not a sentence.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/member/[name]/page.tsx`
**Identity header with stat chips + split facets.** Use `.container-wide`. Keep all fetches.
1. `.entity-header`: breadcrumb (Docket › Member › {name}), h1 = name. Replace the
   `.cite-id ... recorded votes` `.note` with `.stat-chips`: "Sponsored bills"
   (`sponsored.length`), "Recorded votes" (`votes.reduce(...)`, only when >0), and — if the
   activity sparkline data is present — "Years active" from `activity.years`. All derived from
   existing state.
2. Split the single mega-`.panel` into discrete panels (each a peer card):
   - **Sponsored bills**: the existing `.citations`/`.cite-button` list is fine and already
     expands nothing here — keep it, but consider converting to `.data-list`/`.data-row` for
     consistency (title + status-token). Either is acceptable; prefer `.data-row` with a
     `.status-token` for `b.status`.
   - **Vote record**: keep the `.rollcall` summary line (data is only per-vote counts, no full
     roll-call bar available here) — leave as tabular text.
   - **Most-active topics**: keep `.sponsor-list` chips (client-derived, fine).
   - **Activity over time**: use `.section-head` (takeaway + year-range caption) + `Sparkline`
     (endpoint dot flows from Trends update).
3. Not-found → `.empty-state`.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/topic/[slug]/page.tsx`
**Header + trend + brief + sponsors + single-surface bills.** Use `.container-wide`. Keep all
fetches.
1. `.entity-header`: breadcrumb (Docket › Topic › {topic}), h1 = topic. Add `.stat-chips`:
   total matching bills (`bills.length` or, better, keep the brief's `matched_bills` when
   present) and, if trend present, the peak/most-recent year — derive at render only.
2. Trend panel: use `.section-head` (takeaway + year range). Keep `Sparkline` + the
   `.trend-list` year table (tabular already).
3. Advisory briefing: wrap in `.response`; if `brief && !refused` show `.answer` + a
   `.source-divider` "SOURCES" then `CitationList` (as now). If refused/absent, `.empty-state`
   or the calm note (keep calm, not red).
4. Leading sponsors: keep `.sponsor-list`.
5. Recent matching bills: convert the `.bill-row` loop to `.data-list`/`.data-row` with a
   `.status-token`. Keep hrefs/keys.
6. Empty topic → `.empty-state` variant='empty'.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/about/page.tsx`
**Header + coverage as proof.** Keep `.container` (prose page). Keep fetches.
1. `.page-header`: breadcrumb (Docket › About › links to Ask/Browse), keep h1 and lede.
2. "What it is" and "How it works" panels stay; the `.steps` list is fine.
3. "Live coverage": promote the two `.stat`s to `.kpi`/`.kpi-grid` (bigger numbers = proof),
   keep the Jurisdictions `.coverage-jz` list (already a clean row list; optionally convert to
   `.data-list`/`.data-row` for consistency, with the count as `.data-row-meta`). Coverage
   failure → `.error-state` (message text already exists) or keep the existing `status-err`
   note. Source line stays.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/account/page.tsx`
**Calm, centered auth card.** Keep `.container` and all auth logic.
1. Add a `.page-header` (breadcrumb Docket › Sign in / Create account) with a one-line meta:
   "Sync your watchlist across devices." (static copy consistent with the Watchlist hint).
2. Keep the `.panel` + `.auth-form`. Error stays `.status-err`. The `.auth-toggle` stays. No
   structural risk here; just add the header block and remove the ad-hoc top `marginTop` inline
   style in favor of the header's rhythm.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/Nav.tsx`
**Keep the slim top bar; add active state + tighten.** Do NOT build a sidebar (over-engineering
for this scope and would touch layout/routing). Improvements (markup/className only):
1. Add an `aria-current`/active class to the current link. Since Nav can't add hooks per the
   constraint — it already is a client component using `useAuth`; adding `usePathname` is a new
   hook and thus a logic change. **Skip the active state** to respect the constraint; instead
   just keep the existing links. (If the implementer is allowed a purely-presentational
   `usePathname`, gate it behind product approval — default: leave Nav's logic untouched.)
2. Keep brand, links, auth slot. Ensure the auth `.nav-user` email truncates gracefully on
   mobile (add `max-width` + ellipsis via a class if desired). Minimal change file.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/InsightsPanel.tsx`
**Insight-first headers + KPI tiles + bound brief.** Keep every fetch/handler.
1. Replace the `.stats` block with `.kpi-grid`/`.kpi` (total documents, span, top statuses,
   avg-days) using the SAME data. Top-statuses is a compound string — keep it as a `.kpi` with
   the string as `.kpi-num` at a smaller size, or move it to `.kpi-context`.
2. "Legislative activity by topic": use `.section-head` (takeaway + "click a topic for an
   advisory briefing" caption). Keep the `.bars`/`.bar-button` interaction exactly (the click
   handler opens the brief). Keep the `↗ page` `Link`.
3. Brief block: wrap the answer in `.response` semantics; use `.source-divider` before
   `CitationList`. Keep leading-sponsors `.sponsor-list`. The brief failure note stays.
4. Keep the "stay quiet on failure" `return null` — do not change that logic.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/Digest.tsx`
**Freshness card, calm.** Keep fetch/logic (including `return null` on empty/failure).
1. Keep the eyebrow + `.panel`. Convert the two `.citations`/`.cite-button` lists to
   `.data-list`/`.data-row` (or keep `.citations` — it's already clean). Recommended: keep
   `.citations` here since the row is a permalink + title; add a `.status-token` for `it.status`
   in the "Recently enacted" list (data has `status`). Use `.section-head` labels
   ("Recently introduced" / "Recently enacted") if you want captions, else keep
   `.section-title`.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/Watchlist.tsx`
**Empty-state as onboarding; keep card.** Keep ALL storage/auth/merge logic — this file is
logic-heavy, touch JSX only.
1. Keep the eyebrow + `.panel` + `.wl-input-row` form + quick-add `.examples`.
2. The empty state (`hydrated && topics.length === 0`): upgrade the flat `.note` to
   `.empty-state` variant='empty' — title "Track what matters in Council", help
   "Add a topic to get a daily digest of new legislation on it.", and the existing QUICK_TOPICS
   chips ARE the action (they're already rendered above; the empty-state help just points to
   them). Keep the sign-in hint.
3. Per-topic sections: keep `.wl-topic` + `.section-title` + remove button. Convert each
   topic's `.citations` list to `.data-list`/`.data-row` for consistency, or keep `.citations`.
   Keep the "Couldn't load" / "No recent bills" notes calm.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/CitationList.tsx`
**Numbered, tighter, keep expand-in-place.** Keep all toggle/fetch logic — this is a
differentiator.
1. Keep the `.citations`/`.cite-button` structure and inline timeline expand (a genuine edge
   over Perplexity — do NOT remove).
2. Add a stable **number badge** before each `.cite-id`: render the map index+1 in the same
   `.cite-id` monospace/accent so answer text can reference [n]. This is JSX-only
   (`citations.map((c, i) => ...)` already gives `i`).
3. Tighten `.citations li` to a fixed single-line height via CSS (already close). When the
   inline roll-call renders, use `.vote-tally` styling if easy, else keep the existing
   `.rollcall` line. Dissenters are already `Link`s — good; keep.
4. Optionally wrap the whole list in the `.source-grid` visual, but the vertical list is fine
   on the 720px column — priority is numbering + tabular, not a grid.

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/Trends.tsx`
**Sparkline endpoint + accessible label.** Keep the fetch/logic and `panel` prop.
1. In `Sparkline`, after the `<polyline>`, add a `<circle>` at the final point
   (`cx = w`, `cy` = last computed y) `r=2` `fill="var(--accent)"`, and an `aria-label` on the
   `<svg>` summarizing first→last values. Markup only.
2. In the `Trends` list, wrap the title in `.section-head` (takeaway + year-range caption).
   Keep `.trend-list`/`.trend-row`; tabular already present. This improvement propagates to
   member/topic/compare which import `Sparkline`.

---

## 5. What NOT to do (guardrails)

- No second accent color, no gradients beyond the existing faint radial wash, no carousels, no
  entrance/scroll animations, no chart library, no donuts.
- No new fetches, hooks, state, or handler logic. JSX + className + additive CSS only.
- No boxes-in-boxes: prefer `.section-head` + hairline + whitespace over nested panels.
- No card-per-row for long homogeneous lists — use `.data-list`/`.data-row`.
- Refusals and empty states are never red; `--danger` is reserved for real API errors and
  dissent votes.
- No color-only encoding: every status/vote color is paired with text.
- Every number tabular. Every fact one hop from Legistar.
