# Docket — Width & Horizontal-Layout Plan (`DESIGN_LAYOUT.md`)

This plan fixes the one complaint driving this whole run: **"it's too vertical and thin."**
The current redesign traps content in narrow columns (home at 720px; wide pages at 1080px but
still single-column stacks of full-bleed strips) and wastes horizontal space on real monitors.

This is a **layout/width refinement, not a redesign.** It builds on the existing tokens and
component classes already in `globals.css` (`.kpi-grid`, `.detail-grid`, `.detail-side`,
`.data-list`, `.entity-header`, `.response`, `.grounding-pill`, `.breakdown-2`, `.status-token`,
`.section-head`, `.sponsor-list`, `.timeline-rail`, `.vote-tally`, …). We add a wider frame, a
handful of grid utilities, and a prose cap — then re-compose each page's JSX into real columns.

## HARD CONSTRAINT FOR IMPLEMENTERS

Change **only returned JSX structure + `className`s + minimal inline style**, plus additive CSS in
`globals.css`. Do **NOT** touch data fetching, state, hooks, `useEffect`, API calls, event
handlers, or logic. Every data field a page fetches today must still render. No new fetches, no new
components, no new state.

---

## 1. THE WIDTH SYSTEM

The root bug is that **frame width and reading measure are conflated.** The home frame *is* the
720px prose measure, so nothing the app can show escapes reading width. The fix: separate three
tiers and apply them **per region, not per page**.

### Tokens (`:root` in globals.css)

```css
:root {
  /* content widths — THREE tiers now */
  --measure-prose: 700px;   /* readable running text: answer body, about/step copy (~68ch) */
  --measure-wide:  1080px;  /* KEEP for narrow prose-plus pages if referenced; superseded by app */
  --measure-app:   1280px;  /* NEW — the dashboard/app frame (range 1200–1360; 1280 default) */
}
```

- `--measure-prose` drops 720 → **700** and is used as a **child cap on paragraph text**, not as a
  page frame. `.answer` and about copy get `max-inline-size: var(--measure-prose)` so a wide column
  never stretches a sentence past ~68ch. (The existing `.lede` already caps at 60ch — same idea.)
- `--measure-app: 1280px` is the shared **app frame**. It fills a 1440 monitor with ~80px gutters
  and centers calmly on 1920. Never exceed 1360 for text-bearing views.
- `--measure-wide` (1080) stays defined so nothing breaks, but every data page is promoted to
  `--measure-app`.

### Frame containers

```css
/* NEW app frame — the dashboard shell for home + all data pages */
.container-app {
  max-width: var(--measure-app);
  margin: 0 auto;
  padding: 48px 32px 96px;
}

/* keep .container (720) for genuinely prose-only: /account. */
/* .container-wide bumped to the app frame so nothing that referenced it looks skinny. */
.container-wide { max-width: var(--measure-app); }
```

### Nav alignment

`.nav-inner` is pinned at **720px** today — narrower than every content page, so the header
visually detaches. Bump it to the app frame and match its gutter:

```css
.nav-inner { max-width: var(--measure-app); padding: 12px 32px; }
```

### Which width each route uses

| Route | Frame | Interior |
| --- | --- | --- |
| `/` (home) | `.container-app` 1280 | hero band (prose-capped) → 2-col `.app-grid` main + rail |
| `/analytics` | `.container-app` 1280 | KPI band → `.detail-grid` (chart + sponsor rail) → `.breakdown-2` |
| `/browse` | `.container-app` 1280 | full-width header → `.browse-grid` (filter rail + results) |
| `/compare` | `.container-app` 1280 | `.compare-shell` (picker rail + 2-up `.compare-grid`) |
| `/bill/[file_no]` | `.container-app` 1280 | header → `.detail-grid`, main = 2-up `.detail-modules` |
| `/member/[name]` | `.container-app` 1280 | header → `.detail-grid` (bills main + facts rail) |
| `/topic/[slug]` | `.container-app` 1280 | header → `.detail-grid` (brief+bills main / trend+sponsors rail) |
| `/about` | `.container-app` 1280 | full-width header → `.detail-grid` (copy main + coverage rail) |
| `/account` | `.container` 720 | unchanged — pure prose/auth |

### The anti-overcorrection guardrail (non-negotiable)

Widen the FRAME and add COLUMNS. **Never widen a paragraph.** Any block of running prose — the
streamed/final `.answer`, the topic briefing `.answer`, the about "What it is" copy — carries its
own `max-inline-size: var(--measure-prose)` (~68ch). Extra column width becomes left-aligned
breathing room, never a longer line. Lists, bars, chips, rows, sparklines, KPIs are NOT prose and
may use full column width.

---

## 2. GRID UTILITIES (exact CSS to add)

Reuse what exists first. Only three new utilities are needed; the rest is already in `globals.css`.

### Reused as-is
- `.detail-grid` = `minmax(0,1fr) 320px`, `.detail-side` sticky `top:84px`, collapses at 1024px.
  This is the workhorse — used on bill/member/topic already, and now on home/analytics/about.
- `.kpi-grid` = `repeat(auto-fit, minmax(200px,1fr))` — KPI band. Tighten min to 220px (below).
- `.breakdown-2` = `1fr 1fr`, collapses at 720px — analytics paired lists.
- `.compare-grid` = `1fr 1fr`, collapses at 640px — the two compare cards.
- `.data-list` / `.data-row`, `.sponsor-list`, `.timeline-rail`, `.vote-tally`, `.response`.

### NEW utility 1 — home main+rail (`.app-grid`)

A wider primary column than `.detail-grid` (rail 340 vs 320) for the home dashboard body.

```css
.app-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: var(--space-5);          /* 24px */
  align-items: start;
}
.app-rail {                     /* the sticky right rail on home */
  position: sticky;
  top: 84px;
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
@media (max-width: 1024px) {
  .app-grid { grid-template-columns: 1fr; }
  .app-rail { position: static; }
}
```

### NEW utility 2 — browse filter-rail + results (`.browse-grid`)

Mirrors `.detail-grid` but flips it: narrow rail on the LEFT, results on the RIGHT.

```css
.browse-grid {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: var(--space-5);          /* 24px */
  align-items: start;
}
.browse-rail {                  /* sticky filter/actions column */
  position: sticky;
  top: 84px;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
@media (max-width: 1024px) {
  .browse-grid { grid-template-columns: 1fr; }
  .browse-rail { position: static; }
}
```

### NEW utility 3 — nested 2-up module row (`.detail-modules`) + compare shell

`.detail-modules` de-stacks the two main-column modules on the bill page (timeline | roll-call).
`.compare-shell` gives compare a picker rail beside its 2-up grid.

```css
/* bill page: side-by-side timeline + roll-call inside .detail-main */
.detail-modules {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
  gap: var(--space-5);
  align-items: start;
}
@media (max-width: 1024px) {
  .detail-modules { grid-template-columns: 1fr; }
}

/* compare: sticky picker rail + main comparison region */
.compare-shell {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: var(--space-5);
  align-items: start;
}
.compare-rail {
  position: sticky;
  top: 84px;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
@media (max-width: 1024px) {
  .compare-shell { grid-template-columns: 1fr; }
  .compare-rail { position: static; }
}
```

### Prose cap utility

```css
/* running prose stays readable inside any wide column */
.prose,
.response .answer,
.refusal-card .answer {
  max-inline-size: var(--measure-prose);  /* ~68ch */
}
```

Stacking a picker's selects vertically in a rail: the browse filter fields and compare selects use
`.browse-filters`, which is a horizontal `flex-wrap` today. Inside a narrow rail we want them
stacked full-width. Add a rail modifier rather than touching `.browse-filters` globally:

```css
.browse-rail .browse-filters,
.compare-rail .browse-filters { flex-direction: column; gap: var(--space-4); }
.browse-rail .browse-filters > div,
.compare-rail .browse-filters > div { width: 100%; }
.browse-rail .browse-filters input,
.browse-rail .browse-filters select,
.compare-rail .browse-filters select { width: 100%; }
```

### KPI density tweak

```css
.kpi-grid { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
```

Gives a clean 4-across at 1280 for analytics (and 4 KPIs on About/Insights) with no orphan tile.

### Responsive summary
- **≥1024px**: full multi-column (app-grid, browse-grid, detail-grid, detail-modules, compare-shell).
- **≤1024px**: every main+rail and 2-up collapses to one column; sticky rails go static. Uses the
  existing `@media (max-width:1024px)` block — add the new utilities to it.
- **≤720px**: `.breakdown-2` → 1 col (existing).
- **≤640px**: existing gutter tightening; `.container-app` gets `padding: 28px 16px 64px`.

---

## 3. PER-FILE REDESIGN BRIEFS

Order per page: (a) frame swap, (b) column structure, (c) what goes in main vs rail / side-by-side,
(d) prose guard. JSX + className + minimal inline style only.

---

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/globals.css`

Apply §1 tokens/containers and §2 grid utilities. Specifically:
- `:root`: set `--measure-prose: 700px`; add `--measure-app: 1280px`; keep `--measure-wide`.
- Add `.container-app`; set `.container-wide { max-width: var(--measure-app); }`.
- `.nav-inner`: `max-width: var(--measure-app); padding: 12px 32px;`.
- Add `.app-grid` / `.app-rail`, `.browse-grid` / `.browse-rail`, `.detail-modules`,
  `.compare-shell` / `.compare-rail`, the rail `.browse-filters` stacking modifiers, and the
  `.prose` / `.response .answer` / `.refusal-card .answer` `max-inline-size` cap.
- Tighten `.kpi-grid` min to `220px`.
- Extend the existing `@media (max-width:1024px)` block to collapse the four new grids and un-stick
  their rails; add `.container-app` gutter to the `@media (max-width:640px)` block.
- Do NOT remove any existing class.

---

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/Nav.tsx`

No JSX change required — the width fix is entirely in `.nav-inner` CSS. Leave logic untouched.

---

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/page.tsx` (HOME) — biggest win

**Frame:** change `<main className="container">` → `<main className="container-app">`.

**Structure = two regions:**

1. **Hero band (full frame, prose-capped).** Keep the existing `.hero` section: eyebrow, h1,
   `.lede`, `.hero-stats`, the Ask `.panel` (jz select + `.examples` + `.hero-input` form), and the
   streamed / `.response` / `.refusal-card` answer render — all unchanged. To stop the hero content
   itself sprawling across 1280px, cap the hero's inner column: add `style={{ maxWidth: 860 }}` to
   the `.hero` section (or wrap its children) so the ask experience sits in a comfortable ~860px
   block, left-aligned, with the answer body already capped at 68ch via the `.answer` rule. The
   `.hero-stats` row may span the full 860 — they're stat chips, not prose.

2. **Dashboard body (`.app-grid` main + rail).** Replace the three stacked
   `<section className="home-section">` strips (Digest, InsightsPanel, Watchlist) with:

   ```jsx
   <div className="app-grid" style={{ marginTop: 48 }}>
     <div className="detail-main">
       <InsightsPanel jurisdiction={jurisdiction} />
     </div>
     <aside className="app-rail">
       <Digest jurisdiction={jurisdiction} />
       <Watchlist jurisdiction={jurisdiction} />
     </aside>
   </div>
   ```

   - **LEFT MAIN**: `InsightsPanel` — the richest module (KPI grid + topic bars + Trends + on-demand
     brief). It earns the wide column.
   - **RIGHT RAIL (340px sticky)**: `Digest` (public freshness) above `Watchlist` (personal). Both
     are short, glanceable, card-shaped — exactly rail content. This converts three full-width
     strips into an answer-on-top, dashboard-beside-rail layout and kills most of the scroll.

   Note: `home-section` margins are no longer used here; the `.app-grid` gap + the components' own
   `marginTop` inline styles handle spacing. (Digest/Watchlist/InsightsPanel each render their own
   `<section style={{ marginTop }}>` — fine inside a flex rail; optionally the rail's gap makes those
   redundant but they're harmless.)

**Prose guard:** the `.answer` cap (globals.css) keeps the streamed/final answer at ~68ch inside the
hero even though the frame is 1280. No change to answer JSX needed.

**Data:** every field still used — `jurisdictions`/`totalDocuments` (hero-stats + child props),
streamed/result/refusal render, all three child modules unchanged.

---

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/analytics/page.tsx`

**Frame:** already `.container-wide` (now 1280 via CSS). Optionally rename to `.container-app` for
clarity on the three `<main>`s (loading, failed, view, and the Suspense fallback) — either works
since `.container-wide` now equals the app frame. Keep all fetches/state.

**Structure = three bands** (replaces six stacked strips):

1. **BAND 1 — header + KPIs (full width).** Keep `.page-header` and the `.kpi-grid` of four `.kpi`
   tiles exactly as-is; the 220px min gives a clean 4-across at 1280. Keep the `.filter-chips`
   jurisdiction chip.

2. **BAND 2 — `.detail-grid` (chart main + sponsor rail).** Wrap the monthly-volume panel and the
   sponsors panel:

   ```jsx
   <div className="detail-grid">
     <div className="detail-main">
       {/* monthly Introduction-volume .panel (the 24-bar chart) — unchanged inner */}
     </div>
     <aside className="detail-side">
       {/* "Most active sponsors" .panel (top-10 bars, links to /member) — unchanged inner */}
     </aside>
   </div>
   ```

   The tall monthly chart gets the wide column; the sponsor leaderboard is the classic sticky
   right-rail. Keep `Trends` where it makes sense — see Band 3.

3. **BAND 3 — `.breakdown-2` (paired lists).** Put **Trends** (topic sparklines) LEFT and the two
   tiny lists (**Status breakdown** + **Document types**) RIGHT, stacked in the right cell:

   ```jsx
   <div className="breakdown-2">
     <div><Trends jurisdiction={jurisdiction} panel /></div>
     <div style={{ display: "grid", gap: "var(--space-4)" }}>
       {/* Status breakdown .panel */}
       {/* Document types .panel */}
     </div>
   </div>
   ```

   (Trends currently renders between the monthly chart and breakdown-2; move its JSX into Band 3's
   left cell. It's a component call — pure JSX move, no logic touched.)

**Result:** six strips → three bands; the 1280 frame is filled by real columns. No prose here (all
bars/sparklines/numbers), so no measure risk. All grids already collapse at existing breakpoints.

**Data:** total_documents, velocity, enacted, intro-span (KPIs); by_month (main chart); sponsors
(rail); by_status/by_type (breakdown); Trends component — all still rendered.

---

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/browse/page.tsx`

**Frame:** `.container-wide` → `.container-app` (or leave, now equal). Full-width `.page-header`.

**Structure = filter rail + results (`.browse-grid`).** Wrap everything below the header:

```jsx
<div className="browse-grid">
  <aside className="browse-rail">
    <div className="panel">
      <form onSubmit={onSubmit}>
        <div className="browse-filters"> … three fields, now stacked via rail CSS … </div>
        <div className="row"><button …>Browse bills</button></div>
      </form>
    </div>
    {/* active .filter-chips (remove the inline marginTop) */}
    {/* .browse-actions: Export CSV + exportNote moved here */}
  </aside>

  <div className="detail-main">
    {error && <div className="error-state">…</div>}
    {results && (
      <section>
        <div className="toolbar">
          <p className="note">{count line}</p>
          <div className="row" style={{ marginTop: 0 }}>{Prev/Next}</div>
        </div>
        {/* .data-list of .data-row (unchanged), or .empty-state */}
      </section>
    )}
  </div>
</div>
```

- **LEFT RAIL (300px sticky):** the filter form (fields stacked full-width in the rail via the rail
  `.browse-filters` modifier — the ONE place vertical stacking is correct, because these are
  controls), the active `.filter-chips`, and Export CSV + note. Sticky, so filters/export stay
  pinned while paging.
- **RIGHT MAIN:** a `.toolbar` header line with the matching-count note left and Prev/Next
  right-aligned (moved up from the bottom), then the `.data-list` results. Empty/error states stay
  inside this column, verbatim.

Keep all state/setters/CSV/pagination logic. The Prev/Next and Export handlers are moved in the DOM
only. Collapses to the current stacked order at ≤1024px.

**Data:** q/status/jurisdiction filters, results/total/offset, export — all still used.

---

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/compare/page.tsx`

**Frame:** `.container-wide` → `.container-app` on all four returns + the Suspense fallback.

**Structure = picker rail + 2-up (`.compare-shell`).** Keep `.page-header` full-width. Then:

```jsx
<div className="compare-shell">
  <aside className="compare-rail">
    <div className="compare-picker browse-filters">
      {/* Topic A select, Topic B select — now stacked full-width via rail CSS */}
    </div>
    {/* the trailing "← Ask" .note link moves here, under the picker */}
  </aside>

  <div className="detail-main">
    {a && b ? (
      <div className="compare-grid">
        <CompareColumn … /><CompareColumn … />
      </div>
    ) : (
      <div className="empty-state">…</div>
    )}
  </div>
</div>
```

- **LEFT RAIL (260px sticky):** the two `<select>`s stacked, plus the back-link. The picker is short
  controls — a rail is its natural home; the top-strip band is removed.
- **RIGHT MAIN:** the existing `.compare-grid` 2-up now gets the full remaining width (~900px), so
  each `CompareColumn` breathes at ~450px+.

**Inside each `CompareColumn`** (optional, tasteful de-stack): put the `.chip-stat` (Total bills)
and the sparkline side by side instead of stacked. Wrap them:

```jsx
<div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "var(--space-5)",
             alignItems: "center", marginBottom: "var(--space-4)" }}>
  <div className="chip-stat"> … Total bills … </div>
  {showSpark && <div className="chart-frame"><Sparkline series={series} /></div>}
</div>
```

then the "Top sponsors" `.sponsor-list` full-width below. This halves each card's height. Keep the
`.lede` capped (it's in `.page-header`, already ≤60ch) — do not stretch it.

Keep all URL/selection/sponsor-fetch logic. Collapses: `.compare-shell` → 1 col at 1024px,
`.compare-grid` → 1 col at 640px (existing).

**Data:** topics/counts, trends, sponsorsA/B, URL a/b — all still used.

---

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/bill/[file_no]/page.tsx`

**Frame:** already `.container-wide` (now 1280). Keep. The wider frame + rail already exist; the win
is de-stacking the main column and slimming the rail.

**Structure:** keep `.entity-header` (full width) and `.detail-grid`. Two changes:

1. **MAIN column = 2-up `.detail-modules`.** Wrap the Timeline and Roll-call panels side by side:

   ```jsx
   <div className="detail-main">
     <div className="detail-modules">
       <div className="panel">{/* Timeline — .timeline-rail, unchanged */}</div>
       <div className="panel">{/* Roll-call — .vote-tally, unchanged */}</div>
     </div>
     {/* full-width "More from {sponsor}" band moved here, below the modules */}
     {more && more.bills.length > 0 && (
       <div className="panel" style={{ marginTop: "var(--space-5)" }}>
         {/* section-title + .data-list — unchanged inner */}
       </div>
     )}
   </div>
   ```

   Timeline (tall) gets the wider 1.4fr left track; Roll-call (short) the 1fr right track. The
   "More from sponsor" bill list moves OUT of the rail into a full-width band under the modules, so
   its rows breathe instead of wrapping in 320px.

2. **RIGHT RAIL = slimmed.** Drop the redundant "Details" `.panel` (File no / Status / Legistar) —
   Status and Legistar already render in `.page-header-meta`. Keep only **Sponsors**
   (`.sponsor-list`) in the sticky `.detail-side`. Optionally keep a single File-no fact if desired,
   but the header covers identity. Removing Details makes the rail short and clean.

Result: header → [Timeline | Roll-call] + Sponsors rail → full-width related-bills band → back-link.
`.detail-modules` collapses to 1 col at 1024px (add to CSS). Not-found/loading unchanged.

**Data:** timeline, rollcall (tally/votes/dissent), sponsors, more.bills — all still rendered.

---

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/member/[name]/page.tsx`

**Frame:** already `.container-wide` (now 1280). Keep. This page currently ignores its width — five
full-width strips. Adopt the bill page's master+rail.

**Structure:** keep `.entity-header` (name + `.stat-chips`) full-width. Wrap the body in
`.detail-grid`:

```jsx
<div className="detail-grid">
  <div className="detail-main">
    <div className="panel">{/* Sponsored bills — .data-list, unchanged */}</div>
  </div>
  <aside className="detail-side">
    <div className="panel">{/* Vote record — .rollcall line */}</div>
    {topics.length > 0 && <div className="panel">{/* Most-active topics — .sponsor-list */}</div>}
    {hasActivity && <div className="panel">{/* Activity over time — Sparkline */}</div>}
  </aside>
</div>
```

- **MAIN:** the tall "Sponsored bills" `.data-list` (up to 100 rows) — the only scrolling module,
  gets the wide column.
- **RIGHT RAIL (320px sticky):** the three short modules stacked — Vote record (the one-line
  `.rollcall` string, the worst empty-strip offender), Most-active topics, Activity sparkline. All
  narrow-friendly.

The "← Ask" `.note` moves outside `.detail-grid`, full-width at the bottom (as now). Loading/missing
stay on plain `.container-wide`. No new CSS — reuses `.detail-grid`. Collapses at 1024px (existing).

**Data:** sponsored bills, votes record, topics (derived), activity sparkline — all still rendered.

---

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/topic/[slug]/page.tsx`

**Frame:** already `.container-wide` (now 1280). Keep. Adopt `.detail-grid`.

**Structure:** keep `.entity-header` full-width above. Wrap the populated body in `.detail-grid`:

```jsx
<div className="detail-grid">
  <div className="detail-main">
    <div className="panel">
      {/* Advisory briefing — .response/.answer, capped at 68ch via CSS */}
    </div>
    <div className="panel" style={{ marginTop: "var(--space-5)" }}>
      {/* Recent matching bills — .data-list (up to 25) */}
    </div>
  </div>
  <aside className="detail-side">
    {trend && <div className="panel">{/* Activity over time — Sparkline + .trend-list */}</div>}
    <div className="panel">{/* Leading sponsors — .sponsor-list */}</div>
  </aside>
</div>
```

- **MAIN:** the long-form advisory briefing (prose — the `.answer` cap keeps it ~68ch inside the 1fr
  column) then the 25-row bills `.data-list`.
- **RIGHT RAIL (320px sticky):** the compact Activity-over-time trend widget and the Leading-sponsors
  list (the biggest whitespace offender today).

Keep the `entity-header`'s trend chip; the standalone trend panel moves to the rail (the header's
Peak-year chip stays). `empty-state` and loading stay single-column. Back-link full-width below.

**Prose guard:** the briefing `.answer` is capped by the globals rule; no per-file inline needed
(the `.response .answer` selector covers it). If you want belt-and-suspenders, add
`className="answer prose"`.

**Data:** matchCount/peakYear chips, trend, brief+citations, sponsors, bills — all still rendered.

---

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/about/page.tsx`

**Frame:** `.container` (720) → `.container-app` (1280). Full-width `.page-header` (keep the lede at
its 60ch cap).

**Structure = copy main + coverage rail (`.detail-grid`).**

```jsx
<div className="detail-grid">
  <div className="detail-main">
    <div className="panel">{/* "What it is" — prose, add className="prose" or wrap copy */}</div>
    <div className="panel" style={{ marginTop: "var(--space-5)" }}>{/* "How it works" — .steps */}</div>
  </div>
  <aside className="detail-side">
    <div className="panel">{/* "Live coverage": .kpi-grid KPIs + Jurisdictions list + source note */}</div>
  </aside>
</div>
```

- **MAIN (~1fr, prose-capped):** "What it is" paragraph + "How it works" steps stay at readable
  measure. Add `.prose` (or `max-inline-size: var(--measure-prose)`) to the "What it is" paragraph.
- **RIGHT RAIL (320px sticky):** the entire "Live coverage" module — KPIs (the `.kpi-grid` collapses
  to a stacked pair at 320px), the Jurisdictions `.data-list`/`.coverage-jz`, and the source note.
  Keep the loading/failed/loaded conditional intact inside the rail panel.

Reuses `.detail-grid`; collapses at 1024px. Preserve all three fetch states.

**Data:** total_documents + intro-span (KPIs), jurisdictions list, static copy/steps — all rendered.
`by_type/by_status/by_month` stay fetched-but-unused (do not add charts).

---

### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/account/page.tsx`

No layout change. Stays `.container` (720) — pure auth prose. Skip.

---

### Components that need markup changes to fit a rail/grid

These three move into the home `.app-grid`. They render their own `<section style={{ marginTop }}>`
wrappers, which is fine inside a flex rail/main. Minimal-to-no change required, but note:

#### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/InsightsPanel.tsx`
Now lives in the **home main column** (and still standalone on analytics via `Trends`). No structural
change needed — its `.panel` + `.kpi-grid` + `.bars` + brief already fit a wide column. Optional: the
inner `.kpi-grid` now sits in a ~1fr column ~840px wide, so 4 KPIs read as one row — good. Leave
logic and JSX as-is; only the parent wrapper changed. If the on-demand brief's `.answer` should stay
readable, it's already covered by the `.response .answer` cap.

#### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/Digest.tsx`
Now lives in the **home right rail** (340px). Its `.citations` rows are single-line permalinks +
title — they fit a rail fine. No change needed. (If a title looks cramped at 340px, the existing
`overflow-wrap: anywhere` handles it.) Leave `return null`-on-empty logic untouched.

#### `/Users/charlietonneslan/Desktop/task-forge/frontend/app/Watchlist.tsx`
Now lives in the **home right rail**, below Digest. Its input row, quick-add chips, empty-state, and
per-topic `.data-list`s all fit 340px. No change needed. Touch nothing (storage/auth/merge logic is
heavy — leave it).

> These three are listed because their **placement/parent wrapper** changes in `page.tsx`. The
> components' own files need no edits unless a rail-width polish is wanted; if so, it's className-only
> and must not touch fetch/state.

---

## 4. GUARDRAILS (do not overcorrect)

- Frame grows to 1280; **paragraphs never exceed ~68ch** (`--measure-prose` cap on `.answer` /
  about copy). Extra width = margin, not line length.
- Fill width with **more columns**, not fatter panels or longer lines.
- One gap token: **24px (`--space-5`)** between modules desktop; tighten to 16px mobile via existing
  media hooks.
- Cap visible modules above the fold to ~3–5 tiles. Whitespace defines regions; identical card
  chrome (`.panel`) everywhere — hierarchy comes from column span/size, not new borders.
- Every multi-column grid collapses to one column at ≤1024px (rails go static). No exceptions.
- No new fetches, hooks, state, components, colors, or chart libraries. JSX + className + minimal
  inline style + additive CSS only.
```
