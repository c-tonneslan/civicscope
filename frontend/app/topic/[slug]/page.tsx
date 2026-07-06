"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useState } from "react";

import CitationList from "../../CitationList";
import { Sparkline } from "../../Trends";
import { PanelSkeleton } from "../../Skeleton";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Mirrors app/civic/schemas.py: BriefResponse / SponsorsResponse / BillListResponse.
type Citation = { file_no: string; title: string };
type Brief = {
  topic: string;
  matched_bills: number;
  briefing: string;
  citations: Citation[];
  refused: boolean;
};
type Sponsor = { name: string; bills: number };
type BillRow = {
  file_no: string | null;
  title: string | null;
  status: string | null;
  doc_type: string | null;
  intro_date: string | null;
};
type BillListResponse = { bills: BillRow[]; total: number; limit: number; offset: number };
type Trend = { topic: string; series: number[] };
type TrendsData = { years: number[]; topics: Trend[] };

// A shareable per-topic hub: the advisory brief, leading sponsors, and the most
// recent topically-matching bills, all scoped by an optional ?jurisdiction=.
function TopicView({ topic }: { topic: string }) {
  const jurisdiction = useSearchParams().get("jurisdiction") ?? "";

  const [brief, setBrief] = useState<Brief | null>(null);
  const [sponsors, setSponsors] = useState<Sponsor[]>([]);
  const [bills, setBills] = useState<BillRow[]>([]);
  const [trend, setTrend] = useState<{ years: number[]; series: number[] } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    const jz = jurisdiction ? `&jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
    const jzq = jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
    const t = encodeURIComponent(topic);
    // A non-OK response still RESOLVES the fetch, so throw on it to route the
    // page to .catch (empty state) instead of parsing an error body.
    const getJson = async (path: string) => {
      const res = await fetch(`${API_URL}${path}`);
      if (!res.ok) throw new Error(`${path} -> ${res.status}`);
      return res.json();
    };
    Promise.all([
      getJson(`/civic/insights/brief?topic=${t}${jz}`),
      getJson(`/civic/insights/sponsors?topic=${t}${jz}&limit=10`),
      getJson(`/civic/bills?topic=${t}${jz}&limit=25`),
      getJson(`/civic/insights/trends${jzq}`),
    ])
      .then(([b, s, l, tr]: [Brief, { sponsors: Sponsor[] }, BillListResponse, TrendsData]) => {
        if (!live) return;
        setBrief(b);
        setSponsors(s.sponsors ?? []);
        setBills(l.bills ?? []);
        const match = tr.topics.find((x) => x.topic.toLowerCase() === topic.toLowerCase());
        setTrend(match && tr.years.length >= 2 ? { years: tr.years, series: match.series } : null);
      })
      .catch(() => {
        if (!live) return;
        setBrief(null);
        setSponsors([]);
        setBills([]);
        setTrend(null);
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [topic, jurisdiction]);

  const billHref = (fileNo: string) =>
    `/bill/${encodeURIComponent(fileNo)}${
      jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : ""
    }`;

  // Render-time only: dual-encoded status pill class (text always present).
  const statusClass = (status: string | null) => {
    const s = (status ?? "").toUpperCase();
    if (s.includes("ENACTED") || s.includes("ADOPTED")) return "status-token is-ok";
    if (s.includes("FAILED") || s.includes("VETOED") || s.includes("PLACED ON FILE"))
      return "status-token is-danger";
    return "status-token";
  };

  if (loading) {
    return (
      <main className="container-wide">
        <div className="entity-header page-header">
          <p className="breadcrumb">
            <span>Docket</span>
            <span className="sep">›</span>
            <span>Topic</span>
            <span className="sep">›</span>
            <span className="current">{topic}</span>
          </p>
          <h1>{topic}</h1>
        </div>
        <PanelSkeleton lines={5} label="Loading topic" />
      </main>
    );
  }

  const noBrief = !brief || brief.refused;
  const empty = noBrief && sponsors.length === 0 && bills.length === 0;

  // Prefer the brief's authoritative count when present; else the fetched rows.
  const matchCount =
    brief && !brief.refused ? brief.matched_bills : bills.length;
  // Render-derived: the year with the most matching bills (peak), and the last year.
  const peakYear = trend
    ? trend.years[trend.series.indexOf(Math.max(...trend.series))]
    : null;

  return (
    <main className="container-wide">
      <div className="entity-header page-header">
        <p className="breadcrumb">
          <span>Docket</span>
          <span className="sep">›</span>
          <span>Topic</span>
          <span className="sep">›</span>
          <span className="current">{topic}</span>
        </p>
        <h1>{topic}</h1>
        <div className="stat-chips">
          <div className="chip-stat">
            <span className="chip-stat-num">{matchCount}</span>
            <span className="chip-stat-label">Matching bills</span>
          </div>
          {trend && peakYear !== null && (
            <div className="chip-stat">
              <span className="chip-stat-num">{peakYear}</span>
              <span className="chip-stat-label">Peak year</span>
            </div>
          )}
        </div>
      </div>

      {empty ? (
        <div className="empty-state">
          <p className="empty-state-title">No legislative activity yet</p>
          <p className="empty-state-help">
            We have no bills, sponsors, or briefing recorded for this topic.
          </p>
          <div className="empty-state-actions">
            <Link href="/" className="btn-secondary">
              Ask a question
            </Link>
            <Link href="/browse" className="btn-secondary">
              Browse all bills
            </Link>
          </div>
        </div>
      ) : (
        <div className="detail-grid">
          <div className="detail-main">
            <div className="panel">
              <p className="section-title">Advisory briefing</p>
              {brief && !brief.refused ? (
                <div className="response">
                  <p className="answer prose">{brief.briefing}</p>
                  {brief.citations.length > 0 && (
                    <>
                      <p className="source-divider">Sources</p>
                      <CitationList citations={brief.citations} jurisdiction={jurisdiction} />
                    </>
                  )}
                </div>
              ) : (
                <p className="note">
                  No grounded briefing is available for this topic yet.
                </p>
              )}
            </div>

            <div className="panel" style={{ marginTop: "var(--space-5)" }}>
              <p className="section-title">Recent matching bills</p>
              {bills.length > 0 ? (
                <div className="data-list">
                  {bills.map((b, i) => (
                    <Link
                      key={b.file_no ?? `row-${i}`}
                      href={billHref(b.file_no ?? "")}
                      className="data-row"
                    >
                      <span className="data-row-title">
                        #{b.file_no ?? "—"} · {b.title ?? "—"}
                      </span>
                      <span className="data-row-meta">
                        <span className={statusClass(b.status)}>{b.status ?? "—"}</span>
                        {" · "}
                        {b.doc_type ?? "—"} · {b.intro_date ?? "—"}
                      </span>
                    </Link>
                  ))}
                </div>
              ) : (
                <p className="note">No matching bills found.</p>
              )}
            </div>
          </div>

          <aside className="detail-side">
            {trend && (
              <div className="panel">
                <div className="section-head">
                  <p className="section-head-title">Activity over time</p>
                  <p className="section-head-caption">
                    {trend.years[0]}–{trend.years[trend.years.length - 1]} · bills per year
                  </p>
                </div>
                <div className="trends chart-frame">
                  <Sparkline series={trend.series} />
                  <ul className="trend-list">
                    {trend.years.map((y, i) => (
                      <li key={y} className="trend-row">
                        <span className="trend-label">{y}</span>
                        <span className="trend-total">{trend.series[i]}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            <div className="panel">
              <p className="section-title">Leading sponsors on this topic</p>
              {sponsors.length > 0 ? (
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
              ) : (
                <p className="note">No sponsors recorded for this topic yet.</p>
              )}
            </div>
          </aside>
        </div>
      )}

      <p className="note" style={{ marginTop: 24 }}>
        <Link href="/">← Ask</Link>
      </p>
    </main>
  );
}

export default function TopicPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const topic = decodeURIComponent(slug);
  // useSearchParams needs a Suspense boundary in a client page for the
  // production build, so the data-fetching body lives in an inner component.
  return (
    <Suspense
      fallback={
        <main className="container-wide">
          <div className="entity-header page-header">
            <p className="breadcrumb">
              <span>Docket</span>
              <span className="sep">›</span>
              <span className="current">Topic</span>
            </p>
          </div>
          <PanelSkeleton lines={5} label="Loading topic" />
        </main>
      }
    >
      <TopicView topic={topic} />
    </Suspense>
  );
}
