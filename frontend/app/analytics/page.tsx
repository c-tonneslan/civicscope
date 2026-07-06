"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import Trends from "../Trends";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Mirrors app/civic/schemas.py: OverviewResponse / VelocityResponse / SponsorsResponse.
type CountItem = { label: string; count: number };
type Overview = {
  total_documents: number;
  by_type: CountItem[];
  by_status: CountItem[];
  by_month: CountItem[];
  earliest_intro_date: string | null;
  latest_intro_date: string | null;
};
type Velocity = { enacted: number; avg_days_to_enact: number | null };
type Sponsor = { name: string; bills: number };

// Newest ~24 months keep the monthly-volume chart compact on a long corpus.
const MONTHS_SHOWN = 24;

// Compact horizontal bars for one labelled breakdown (status / doc-type).
function BarBreakdown({ items }: { items: CountItem[] }) {
  const max = items.reduce((m, i) => Math.max(m, i.count), 1);
  return (
    <ul className="bars">
      {items.map((i) => (
        <li key={i.label} className="bar-row">
          <span className="bar-label">{i.label}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${(i.count / max) * 100}%` }} />
          </span>
          <span className="bar-value">{i.count}</span>
        </li>
      ))}
    </ul>
  );
}

// Whole-corpus dashboard: velocity headline, monthly volume, status/type
// breakdowns, topic trends, and the most active sponsors overall.
function AnalyticsView() {
  const jurisdiction = useSearchParams().get("jurisdiction") ?? "";

  const [overview, setOverview] = useState<Overview | null>(null);
  const [velocity, setVelocity] = useState<Velocity | null>(null);
  const [sponsors, setSponsors] = useState<Sponsor[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setFailed(false);
    const qs = jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
    // Compose the sponsors query without doubling the '?' when a jurisdiction
    // is already present.
    const sponsorQs = `${qs ? `${qs}&` : "?"}limit=10`;
    // Any non-OK response still RESOLVES the fetch, so throw to route the page
    // to a single failed state instead of parsing an error body.
    const getJson = async (path: string) => {
      const res = await fetch(`${API_URL}${path}`);
      if (!res.ok) throw new Error(`${path} -> ${res.status}`);
      return res.json();
    };
    Promise.all([
      getJson(`/civic/insights/overview${qs}`),
      getJson(`/civic/insights/velocity${qs}`),
      getJson(`/civic/insights/sponsors${sponsorQs}`),
    ])
      .then(([o, v, s]: [Overview, Velocity, { sponsors: Sponsor[] }]) => {
        if (!live) return;
        setOverview(o);
        setVelocity(v);
        setSponsors(s.sponsors ?? []);
      })
      .catch(() => live && setFailed(true))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [jurisdiction]);

  if (loading) {
    return (
      <main className="container">
        <p className="eyebrow">civicscope · Analytics</p>
        <p className="note">Loading analytics…</p>
      </main>
    );
  }

  if (failed || !overview) {
    return (
      <main className="container">
        <p className="eyebrow">civicscope · Analytics</p>
        <h1>Analytics</h1>
        <p className="note">Analytics are unavailable right now. Try again shortly.</p>
        <p className="note" style={{ marginTop: 24 }}>
          <Link href="/">← Ask</Link>
        </p>
      </main>
    );
  }

  // by_month arrives ascending ('YYYY-MM'); the newest tail reads left-to-right
  // with the latest month last.
  const months = overview.by_month.slice(-MONTHS_SHOWN);
  const maxMonth = months.reduce((m, i) => Math.max(m, i.count), 1);
  const trimmed = overview.by_month.length > months.length;

  return (
    <main className="container">
      <p className="eyebrow">civicscope · Analytics</p>
      <h1>Analytics{jurisdiction ? ` · ${jurisdiction}` : ""}</h1>
      <p className="note">A whole-corpus view of legislative activity, velocity, and sponsorship.</p>

      <div className="panel">
        <div className="stats">
          <div className="stat">
            <span className="stat-num">{overview.total_documents.toLocaleString()}</span>
            <span className="stat-label">bills &amp; resolutions</span>
          </div>
          {velocity && (
            <div className="stat">
              <span className="stat-num">
                {velocity.avg_days_to_enact != null
                  ? `~${velocity.avg_days_to_enact} days`
                  : "—"}
              </span>
              <span className="stat-label">avg time to enact</span>
            </div>
          )}
          {velocity && (
            <div className="stat">
              <span className="stat-num">{velocity.enacted.toLocaleString()}</span>
              <span className="stat-label">bills enacted</span>
            </div>
          )}
          {overview.earliest_intro_date && overview.latest_intro_date && (
            <div className="stat">
              <span className="stat-num">
                {overview.earliest_intro_date} → {overview.latest_intro_date}
              </span>
              <span className="stat-label">introduced-date span</span>
            </div>
          )}
        </div>
      </div>

      {months.length > 0 && (
        <div className="panel">
          <p className="section-title">
            Monthly introduction volume{" "}
            <span className="hint">
              {trimmed ? `— last ${MONTHS_SHOWN} months (newest last)` : "— newest last"}
            </span>
          </p>
          <ul className="bars">
            {months.map((m) => (
              <li key={m.label} className="bar-row">
                <span className="bar-label">{m.label}</span>
                <span className="bar-track">
                  <span
                    className="bar-fill"
                    style={{ width: `${(m.count / maxMonth) * 100}%` }}
                  />
                </span>
                <span className="bar-value">{m.count}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <Trends jurisdiction={jurisdiction} panel />

      {overview.by_status.length > 0 && (
        <div className="panel">
          <p className="section-title">Status breakdown</p>
          <BarBreakdown items={overview.by_status} />
        </div>
      )}

      {overview.by_type.length > 0 && (
        <div className="panel">
          <p className="section-title">Document types</p>
          <BarBreakdown items={overview.by_type} />
        </div>
      )}

      {sponsors.length > 0 && (
        <div className="panel">
          <p className="section-title">Most active sponsors</p>
          <ul className="sponsor-list">
            {sponsors.map((s) => (
              <li key={s.name}>
                <Link className="sponsor-name" href={`/member/${encodeURIComponent(s.name)}`}>
                  {s.name}
                </Link>
                <span className="sponsor-count">{s.bills} bills</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="note" style={{ marginTop: 24 }}>
        <Link href="/">← Ask</Link>
      </p>
    </main>
  );
}

export default function AnalyticsPage() {
  // useSearchParams needs a Suspense boundary in a client page for the
  // production build, so the data-fetching body lives in an inner component.
  return (
    <Suspense
      fallback={
        <main className="container">
          <p className="eyebrow">civicscope · Analytics</p>
          <p className="note">Loading analytics…</p>
        </main>
      }
    >
      <AnalyticsView />
    </Suspense>
  );
}
