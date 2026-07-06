"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Mirrors app/civic/schemas.py: OverviewResponse and the /civic/jurisdictions
// payload. Duplicated (no shared types module) — res.ok guards + null-checks
// keep runtime safe if the backend fields drift.
type CountItem = { label: string; count: number };
type Overview = {
  total_documents: number;
  by_type: CountItem[];
  by_status: CountItem[];
  by_month: CountItem[];
  earliest_intro_date: string | null;
  latest_intro_date: string | null;
};
type Jurisdiction = { slug: string; documents: number };

export default function AboutPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [jurisdictions, setJurisdictions] = useState<Jurisdiction[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    // Any non-OK response still RESOLVES the fetch, so guard with res.ok and
    // throw — that routes 404s/500s to .catch and the static prose below stays
    // readable instead of rendering undefined coverage.
    const getJson = async (path: string) => {
      const res = await fetch(`${API_URL}${path}`);
      if (!res.ok) throw new Error(`${path} -> ${res.status}`);
      return res.json();
    };
    Promise.all([
      getJson("/civic/insights/overview"),
      getJson("/civic/jurisdictions"),
    ])
      .then(([o, j]: [Overview, { jurisdictions: Jurisdiction[] }]) => {
        if (!live) return;
        setOverview(o);
        setJurisdictions(j.jurisdictions ?? []);
      })
      .catch(() => live && setFailed(true))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, []);

  const sortedJz = [...jurisdictions].sort((a, b) => b.documents - a.documents);

  return (
    <main className="container">
      <header className="page-header">
        <p className="breadcrumb">
          <Link href="/">Docket</Link>
          <span className="sep">›</span>
          <Link href="/">Ask</Link>
          <span className="sep">›</span>
          <Link href="/browse">Browse</Link>
          <span className="sep">›</span>
          <span className="current">About</span>
        </p>
        <h1>About Docket</h1>
        <p className="lede">
          Docket turns the public record of local legislation into plain,
          answerable questions — grounded in the real documents, or an honest
          no when the records don&apos;t support an answer.
        </p>
      </header>

      <div className="panel">
        <p className="section-title">What it is</p>
        <p className="answer">
          Ask a plain-English question about local legislation and Docket
          answers from the actual bill text, with citations you can open and
          read for yourself. When the records don&apos;t support a confident
          answer, it refuses rather than guessing — the goal is trust, not the
          appearance of one.
        </p>
      </div>

      <div className="panel">
        <p className="section-title">How it works</p>
        <ol className="steps">
          <li>Ingest bill text from the Legistar public API.</li>
          <li>Retrieve the relevant passages with a hybrid dense + lexical search.</li>
          <li>Synthesize a cite-or-refuse answer with a local LLM.</li>
          <li>Enrich each bill with its sponsors, timeline, and roll-call votes.</li>
        </ol>
      </div>

      <div className="panel">
        <p className="eyebrow">Live coverage</p>
        {loading && <p className="note">Loading coverage…</p>}
        {!loading && failed && (
          <div className="error-state">
            <p className="error-state-msg">
              Coverage is unavailable — the Docket API may be offline. The rest
              of this page still describes how Docket works.
            </p>
          </div>
        )}
        {!loading && !failed && (
          <>
            {overview && typeof overview.total_documents === "number" && (
              <div className="kpi-grid">
                <div className="kpi">
                  <span className="kpi-num">
                    {overview.total_documents.toLocaleString()}
                  </span>
                  <span className="kpi-label">bills &amp; resolutions</span>
                </div>
                {overview.earliest_intro_date && overview.latest_intro_date && (
                  <div className="kpi">
                    <span className="kpi-num">
                      {overview.earliest_intro_date} → {overview.latest_intro_date}
                    </span>
                    <span className="kpi-label">introduced-date span</span>
                  </div>
                )}
              </div>
            )}

            <p className="section-title">Jurisdictions</p>
            {sortedJz.length > 0 ? (
              <div className="data-list">
                {sortedJz.map((j) => (
                  <div className="data-row" key={j.slug}>
                    <span className="data-row-title">{j.slug}</span>
                    <span className="data-row-meta">
                      {j.documents.toLocaleString()} bills
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="note">No jurisdictions reported.</p>
            )}

            <p className="note">Source: the Legistar public API.</p>
          </>
        )}
      </div>
    </main>
  );
}
