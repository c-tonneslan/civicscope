"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Mirrors app/civic/schemas.py: OverviewResponse / TopicActivityResponse.
type CountItem = { label: string; count: number };
type Overview = {
  total_documents: number;
  by_type: CountItem[];
  by_status: CountItem[];
  by_month: CountItem[];
  earliest_intro_date: string | null;
  latest_intro_date: string | null;
};
type TopicItem = { topic: string; bills: number };
type Topics = { since: string | null; topics: TopicItem[] };

export default function InsightsPanel({ jurisdiction = "" }: { jurisdiction?: string }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [topics, setTopics] = useState<TopicItem[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setFailed(false);
    const qs = jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
    // Treat any non-OK response as a failure (a 404 from an un-restarted backend,
    // or a 500) — those still RESOLVE the fetch, so without the res.ok guard we'd
    // parse an error body and render undefined fields. Throwing routes them to
    // .catch, which hides the panel instead of crashing the page.
    const getJson = async (path: string) => {
      const res = await fetch(`${API_URL}${path}`);
      if (!res.ok) throw new Error(`${path} -> ${res.status}`);
      return res.json();
    };
    Promise.all([
      getJson(`/civic/insights/overview${qs}`),
      getJson(`/civic/insights/topics${qs}`),
    ])
      .then(([o, t]: [Overview, Topics]) => {
        if (!live) return;
        setOverview(o);
        setTopics(t.topics);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [jurisdiction]);

  // Stay quiet unless the data is there — insights are a bonus view, so a backend
  // that isn't up must never break the Ask experience above.
  if (failed || (!overview && !topics)) return null;

  const maxBills = topics?.reduce((m, t) => Math.max(m, t.bills), 0) ?? 0;

  return (
    <section className="insights" style={{ marginTop: 32 }}>
      <p className="eyebrow">civicscope · Insights</p>
      <div className="panel">
        {overview && typeof overview.total_documents === "number" && (
          <div className="stats">
            <div className="stat">
              <span className="stat-num">{overview.total_documents.toLocaleString()}</span>
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
            <div className="stat">
              <span className="stat-num">
                {overview.by_status.slice(0, 3).map((s) => `${s.label} ${s.count}`).join(" · ")}
              </span>
              <span className="stat-label">top statuses</span>
            </div>
          </div>
        )}

        {topics && topics.length > 0 && (
          <>
            <p className="section-title">Legislative activity by topic</p>
            <ul className="bars">
              {topics.map((t) => (
                <li key={t.topic} className="bar-row">
                  <span className="bar-label">{t.topic}</span>
                  <span className="bar-track">
                    <span
                      className="bar-fill"
                      style={{ width: `${maxBills ? (t.bills / maxBills) * 100 : 0}%` }}
                    />
                  </span>
                  <span className="bar-value">{t.bills}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}
