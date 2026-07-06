"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useState } from "react";

import { PanelSkeleton } from "../../Skeleton";

// Base URL the browser uses to reach the FastAPI backend. Inlined at build
// time by Next because of the NEXT_PUBLIC_ prefix; falls back to the local
// backend port so the app works out of the box.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Bill = {
  file_no: string | null;
  title: string | null;
  status: string | null;
  doc_type: string | null;
  intro_date: string | null;
};
type Bills = { bills: Bill[]; total: number };
type RecordItem = { vote: string; bills: number };
type MemberRecord = { person: string; record: RecordItem[] };
type MemberActivity = {
  person: string;
  jurisdiction: string | null;
  years: number[];
  series: number[];
};

// Copied from Trends.tsx (same shape) so this hub stays self-contained, matching
// how the page inlines TOPIC_KEYWORDS rather than importing shared constants.
function Sparkline({ series }: { series: number[] }) {
  if (series.length < 2) return null;
  const w = 150;
  const h = 26;
  const max = Math.max(...series, 1);
  const pts = series
    .map((v, i) => `${(i / (series.length - 1)) * w},${h - (v / max) * (h - 2) - 1}`)
    .join(" ");
  return (
    <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth="1.5" />
    </svg>
  );
}

// A lightweight topic tally derived client-side from sponsored-bill titles,
// keyed off the same TRACKED_TOPICS labels the backend uses (insights.py). This
// avoids a new endpoint; matching is substring/keyword only, so it's a hint.
const TOPIC_KEYWORDS: [string, string[]][] = [
  ["Housing", ["housing", "affordable", "rent", "eviction", "tenant", "landlord"]],
  ["Zoning & Land Use", ["zoning", "rezone", "overlay", "redevelopment", "subdivision"]],
  ["Transit & Streets", ["transit", "septa", "traffic", "parking", "bicycle", "pedestrian"]],
  ["Public Safety", ["police", "crime", "firearm", "gun", "violence", "safety"]],
  ["Education", ["school", "education", "student", "teacher", "scholarship"]],
  ["Budget & Taxes", ["budget", "tax", "appropriation", "fiscal", "levy", "revenue"]],
  ["Health", ["health", "hospital", "opioid", "medical", "mental"]],
  ["Environment", ["environment", "climate", "energy", "recycling", "stormwater"]],
  ["Jobs & Labor", ["worker", "wage", "employment", "labor", "union"]],
];

// Dual-encoded status pill class from a bill's status string. Render-time only;
// the label text always carries the meaning, color merely reinforces it.
function statusTokenClass(status: string | null): string {
  const s = (status ?? "").toUpperCase();
  if (s.includes("ENACTED") || s.includes("ADOPTED")) return "status-token is-ok";
  if (s.includes("FAILED") || s.includes("VETOED") || s.includes("PLACED ON FILE"))
    return "status-token is-danger";
  return "status-token";
}

function topTopics(bills: Bill[]): { topic: string; bills: number }[] {
  const counts = new Map<string, number>();
  for (const b of bills) {
    const t = (b.title ?? "").toLowerCase();
    for (const [label, words] of TOPIC_KEYWORDS) {
      if (words.some((w) => t.includes(w))) {
        counts.set(label, (counts.get(label) ?? 0) + 1);
      }
    }
  }
  return [...counts.entries()]
    .map(([topic, n]) => ({ topic, bills: n }))
    .sort((a, b) => b.bills - a.bills)
    .slice(0, 5);
}

// A shareable per-member hub aggregating the Matters a council member sponsored
// (via the /civic/bills ?sponsor= filter), their roll-call record (/insights/
// member), and a client-derived breakdown of their most-active topics.
function MemberView({ name }: { name: string }) {
  const jurisdiction = useSearchParams().get("jurisdiction") ?? "";

  const [bills, setBills] = useState<Bills | null>(null);
  const [record, setRecord] = useState<MemberRecord | null>(null);
  const [activity, setActivity] = useState<MemberActivity | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    const jz = jurisdiction ? `&jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
    const p = encodeURIComponent(name);
    // Any non-OK response still RESOLVES the fetch, so throw on it to route the
    // page to .catch (which renders not-found) instead of parsing an error body.
    const getJson = async (path: string) => {
      const res = await fetch(`${API_URL}${path}`);
      if (!res.ok) throw new Error(`${path} -> ${res.status}`);
      return res.json();
    };
    Promise.all([
      getJson(`/civic/bills?sponsor=${p}&limit=100${jz}`),
      getJson(`/civic/insights/member?person=${p}${jz}`),
    ])
      .then(([b, r]: [Bills, MemberRecord]) => {
        if (!live) return;
        setBills(b);
        setRecord(r);
      })
      .catch(() => {
        if (!live) return;
        setBills(null);
        setRecord(null);
      })
      .finally(() => live && setLoading(false));
    // Decoupled from the Promise.all above so a member-activity outage only hides
    // the sparkline instead of tripping the shared .catch (which renders not-found).
    getJson(`/civic/insights/member-activity?person=${p}${jz}`)
      .then((a: MemberActivity) => live && setActivity(a))
      .catch(() => live && setActivity(null));
    return () => {
      live = false;
    };
  }, [name, jurisdiction]);

  if (loading) {
    return (
      <main className="container-wide">
        <nav className="breadcrumb" aria-label="Breadcrumb">
          <Link href="/">Docket</Link>
          <span className="sep">›</span>
          <span className="current">Member</span>
        </nav>
        <PanelSkeleton lines={6} label="Loading member" />
      </main>
    );
  }

  const sponsored = bills?.bills ?? [];
  const votes = record?.record ?? [];
  // Nothing on either surface -> the member is absent from the corpus.
  const missing = sponsored.length === 0 && votes.length === 0;
  if (missing) {
    return (
      <main className="container-wide">
        <nav className="breadcrumb" aria-label="Breadcrumb">
          <Link href="/">Docket</Link>
          <span className="sep">›</span>
          <span className="current">Member</span>
        </nav>
        <div className="empty-state">
          <p className="empty-state-title">No record found for {name}</p>
          <p className="empty-state-help">
            This member has no sponsored bills or roll-call votes in the corpus.
          </p>
          <div className="empty-state-actions">
            <Link href="/" className="btn-secondary">
              ← Ask
            </Link>
          </div>
        </div>
      </main>
    );
  }

  const topics = topTopics(sponsored);
  const jzQuery = jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
  const recordedVotes = votes.reduce((n, v) => n + v.bills, 0);
  const hasActivity = activity !== null && activity.years.length >= 2;

  return (
    <main className="container-wide">
      <header className="entity-header">
        <nav className="breadcrumb" aria-label="Breadcrumb">
          <Link href="/">Docket</Link>
          <span className="sep">›</span>
          <span>Member</span>
          <span className="sep">›</span>
          <span className="current">{name}</span>
        </nav>
        <h1>{name}</h1>
        <div className="stat-chips">
          <div className="chip-stat">
            <span className="chip-stat-num">{sponsored.length}</span>
            <span className="chip-stat-label">Sponsored bills</span>
          </div>
          {votes.length > 0 && (
            <div className="chip-stat">
              <span className="chip-stat-num">{recordedVotes}</span>
              <span className="chip-stat-label">Recorded votes</span>
            </div>
          )}
          {hasActivity && (
            <div className="chip-stat">
              <span className="chip-stat-num">
                {activity.years[activity.years.length - 1] - activity.years[0] + 1}
              </span>
              <span className="chip-stat-label">Years active</span>
            </div>
          )}
        </div>
      </header>

      <div className="detail-grid">
        <div className="detail-main">
          <div className="panel">
            <p className="section-title">Sponsored bills</p>
            {sponsored.length > 0 ? (
              <div className="data-list">
                {sponsored.map((b) => {
                  const row = (
                    <>
                      <span className="data-row-title">
                        {b.file_no ? (
                          <>
                            <span className="cite-id">#{b.file_no}</span> {b.title ?? "Untitled"}
                          </>
                        ) : (
                          b.title ?? "Untitled"
                        )}
                      </span>
                      {b.status && (
                        <span className="data-row-meta">
                          <span className={statusTokenClass(b.status)}>{b.status}</span>
                        </span>
                      )}
                    </>
                  );
                  return b.file_no ? (
                    <Link
                      key={b.file_no}
                      className="data-row"
                      href={`/bill/${encodeURIComponent(b.file_no)}${jzQuery}`}
                    >
                      {row}
                    </Link>
                  ) : (
                    <div className="data-row" key={b.title}>
                      {row}
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="note">No sponsored bills on record for this member.</p>
            )}
          </div>
        </div>

        <aside className="detail-side">
          <div className="panel">
            <p className="section-title">Vote record</p>
            {votes.length > 0 ? (
              <p className="rollcall">{votes.map((v) => `${v.vote} ${v.bills}`).join(" · ")}</p>
            ) : (
              <p className="note">No roll-call votes on record for this member.</p>
            )}
          </div>

          {topics.length > 0 && (
            <div className="panel">
              <p className="section-title">Most-active topics</p>
              <ul className="sponsor-list">
                {topics.map((t) => (
                  <li key={t.topic}>
                    <span className="sponsor-name">{t.topic}</span>
                    <span className="sponsor-count">{t.bills} bills</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {hasActivity && (
            <div className="panel">
              <div className="section-head">
                <p className="section-head-title">Activity over time</p>
                <p className="section-head-caption">
                  {activity.years[0]}–{activity.years[activity.years.length - 1]} · bills per year
                </p>
              </div>
              <div className="chart-frame">
                <Sparkline series={activity.series} />
              </div>
            </div>
          )}
        </aside>
      </div>

      <p className="note" style={{ marginTop: 24 }}>
        <Link href="/">← Ask</Link>
      </p>
    </main>
  );
}

export default function MemberPage({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name } = use(params);
  // Member names carry spaces/periods and arrive URL-encoded; a malformed value
  // (stray %) would throw, so fall back to the raw segment rather than crash.
  let memberName = name;
  try {
    memberName = decodeURIComponent(name);
  } catch {
    memberName = name;
  }
  // useSearchParams needs a Suspense boundary in a client page for the
  // production build, so the data-fetching body lives in an inner component.
  return (
    <Suspense
      fallback={
        <main className="container-wide">
          <nav className="breadcrumb" aria-label="Breadcrumb">
            <Link href="/">Docket</Link>
            <span className="sep">›</span>
            <span className="current">Member</span>
          </nav>
          <PanelSkeleton lines={6} label="Loading member" />
        </main>
      }
    >
      <MemberView name={memberName} />
    </Suspense>
  );
}
