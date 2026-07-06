"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import Trends from "../Trends";
import { PanelSkeleton } from "../Skeleton";

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
      <main className="container-wide">
        <div className="page-header">
          <p className="breadcrumb">
            <span className="current">Docket</span>
            <span className="sep">›</span>
            <span className="current">Analytics</span>
          </p>
          <h1>Analytics</h1>
        </div>
        <div className="kpi-grid" aria-label="Loading analytics" aria-busy="true">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="kpi">
              <span className="skeleton skeleton-line" style={{ width: "45%" }} />
              <span className="skeleton skeleton-title" style={{ width: "70%", marginBottom: 0 }} />
            </div>
          ))}
        </div>
        <div className="panel">
          <span className="skeleton skeleton-title" />
          <div className="bars">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <span key={i} className="skeleton skeleton-line" style={{ width: `${90 - i * 12}%` }} />
            ))}
          </div>
        </div>
      </main>
    );
  }

  if (failed || !overview) {
    return (
      <main className="container-wide">
        <div className="page-header">
          <p className="breadcrumb">
            <span className="current">Docket</span>
            <span className="sep">›</span>
            <span className="current">Analytics</span>
          </p>
          <h1>Analytics</h1>
        </div>
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
  const maxSponsor = sponsors.reduce((m, s) => Math.max(m, s.bills), 1);

  return (
    <main className="container-wide">
      <div className="page-header">
        <p className="breadcrumb">
          <Link href="/">Docket</Link>
          <span className="sep">›</span>
          <span className="current">Analytics</span>
        </p>
        <h1>Analytics{jurisdiction ? ` · ${jurisdiction}` : ""}</h1>
        <p className="page-header-meta">
          A whole-corpus view of legislative activity, velocity, and sponsorship.
        </p>
      </div>

      {jurisdiction && (
        <div className="filter-chips">
          <span className="example-chip" aria-disabled="true">
            Jurisdiction: {jurisdiction}
          </span>
        </div>
      )}

      <div className="kpi-grid">
        <Link className="kpi kpi-link" href="/browse">
          <span className="kpi-label">Bills &amp; resolutions</span>
          <span className="kpi-num">{overview.total_documents.toLocaleString()}</span>
          <span className="kpi-context">Browse the full corpus →</span>
        </Link>
        {velocity && (
          <div className="kpi">
            <span className="kpi-label">Avg time to enact</span>
            <span className="kpi-num">
              {velocity.avg_days_to_enact != null
                ? `~${velocity.avg_days_to_enact} days`
                : "—"}
            </span>
            <span className="kpi-context">Introduction to enactment</span>
          </div>
        )}
        {velocity && (
          <Link className="kpi kpi-link" href="/browse?status=ENACTED">
            <span className="kpi-label">Bills enacted</span>
            <span className="kpi-num">{velocity.enacted.toLocaleString()}</span>
            <span className="kpi-context">Browse enacted →</span>
          </Link>
        )}
        {overview.earliest_intro_date && overview.latest_intro_date && (
          <div className="kpi">
            <span className="kpi-label">Introduced-date span</span>
            <span className="kpi-num" style={{ fontSize: "1.1rem" }}>
              {overview.earliest_intro_date} → {overview.latest_intro_date}
            </span>
            <span className="kpi-context">First to most recent</span>
          </div>
        )}
      </div>

      {months.length > 0 && (
        <div className="panel">
          <div className="section-head">
            <p className="section-head-title">
              Introduction volume, last {months.length} months
            </p>
            <p className="section-head-caption">
              {trimmed
                ? `last ${MONTHS_SHOWN} months · newest last · current month partial`
                : "newest last · current month partial"}
            </p>
          </div>
          <ul className="bars chart-frame">
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

      {(overview.by_status.length > 0 || overview.by_type.length > 0) && (
        <div className="breakdown-2">
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
        </div>
      )}

      {sponsors.length > 0 && (
        <div className="panel">
          <p className="section-title">Most active sponsors</p>
          <ul className="bars">
            {sponsors.map((s) => (
              <li key={s.name} className="bar-row">
                <Link className="bar-label" href={`/member/${encodeURIComponent(s.name)}`}>
                  {s.name}
                </Link>
                <span className="bar-track">
                  <span
                    className="bar-fill"
                    style={{ width: `${(s.bills / maxSponsor) * 100}%` }}
                  />
                </span>
                <span className="bar-value">{s.bills}</span>
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
        <main className="container-wide">
          <div className="page-header">
            <p className="breadcrumb">
              <span className="current">Docket</span>
              <span className="sep">›</span>
              <span className="current">Analytics</span>
            </p>
            <h1>Analytics</h1>
          </div>
          <PanelSkeleton lines={6} label="Loading analytics" />
        </main>
      }
    >
      <AnalyticsView />
    </Suspense>
  );
}
