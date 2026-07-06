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

  if (loading) {
    return (
      <main className="container">
        <p className="eyebrow">Docket · Topic</p>
        <h1>{topic}</h1>
        <PanelSkeleton lines={5} label="Loading topic" />
      </main>
    );
  }

  const noBrief = !brief || brief.refused;
  const empty = noBrief && sponsors.length === 0 && bills.length === 0;

  return (
    <main className="container">
      <p className="eyebrow">Docket · Topic</p>
      <h1>{topic}</h1>

      {trend && (
        <div className="panel">
          <p className="section-title">
            Activity over time{" "}
            <span className="hint">
              — {trend.years[0]}–{trend.years[trend.years.length - 1]} (bills/year)
            </span>
          </p>
          <div className="trends">
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

      {empty ? (
        <p className="note">No legislative activity found for this topic yet.</p>
      ) : (
        <>
          <div className="panel">
            <p className="section-title">
              Advisory briefing
              {brief && !brief.refused ? ` · ${brief.matched_bills} matching bills` : ""}
            </p>
            {brief && !brief.refused ? (
              <>
                <p className="answer">{brief.briefing}</p>
                {brief.citations.length > 0 && (
                  <CitationList citations={brief.citations} jurisdiction={jurisdiction} />
                )}
              </>
            ) : (
              <p className="note">No briefing available for this topic.</p>
            )}
          </div>

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

          <div className="panel">
            <p className="section-title">Recent matching bills</p>
            {bills.length > 0 ? (
              bills.map((b, i) => (
                <Link
                  key={b.file_no ?? `row-${i}`}
                  href={billHref(b.file_no ?? "")}
                  className="bill-row"
                >
                  <span className="bill-row-title">
                    #{b.file_no ?? "—"} · {b.title ?? "—"}
                  </span>
                  <span className="bill-row-meta">
                    {b.status ?? "—"} · {b.doc_type ?? "—"} · {b.intro_date ?? "—"}
                  </span>
                </Link>
              ))
            ) : (
              <p className="note">No matching bills found.</p>
            )}
          </div>
        </>
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
        <main className="container">
          <p className="eyebrow">Docket · Topic</p>
          <PanelSkeleton lines={5} label="Loading topic" />
        </main>
      }
    >
      <TopicView topic={topic} />
    </Suspense>
  );
}
