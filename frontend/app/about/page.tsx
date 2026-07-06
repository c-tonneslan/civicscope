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
      <p className="eyebrow">
        civicscope · <Link href="/">Ask</Link> ·{" "}
        <Link href="/browse">Browse all bills</Link>
      </p>
      <h1>About civicscope</h1>
      <p className="lede">
        civicscope turns the public record of local legislation into plain,
        answerable questions — grounded in the real documents, or an honest no
        when the records don&apos;t support an answer.
      </p>

      <div className="panel">
        <p className="section-title">What it is</p>
        <p className="answer">
          Ask a plain-English question about local legislation and civicscope
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
          <p className="note status-err">
            Coverage is unavailable — the civicscope API may be offline. The rest
            of this page still describes how civicscope works.
          </p>
        )}
        {!loading && !failed && (
          <>
            {overview && typeof overview.total_documents === "number" && (
              <div className="stats">
                <div className="stat">
                  <span className="stat-num">
                    {overview.total_documents.toLocaleString()}
                  </span>
                  <span className="stat-label">bills &amp; resolutions</span>
                </div>
                {overview.earliest_intro_date && overview.latest_intro_date && (
                  <div className="stat">
                    <span className="stat-num">
                      {overview.earliest_intro_date} → {overview.latest_intro_date}
                    </span>
                    <span className="stat-label">introduced-date span</span>
                  </div>
                )}
              </div>
            )}

            <p className="section-title">Jurisdictions</p>
            {sortedJz.length > 0 ? (
              <ul className="coverage-jz">
                {sortedJz.map((j) => (
                  <li key={j.slug}>
                    <span>{j.slug}</span>
                    <span className="coverage-jz-count">
                      {j.documents.toLocaleString()} bills
                    </span>
                  </li>
                ))}
              </ul>
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
