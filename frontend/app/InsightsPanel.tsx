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
type Citation = { file_no: string; title: string };
type Brief = {
  topic: string;
  matched_bills: number;
  briefing: string;
  citations: Citation[];
  refused: boolean;
};
type Sponsor = { name: string; bills: number };

export default function InsightsPanel({ jurisdiction = "" }: { jurisdiction?: string }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [topics, setTopics] = useState<TopicItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [sponsors, setSponsors] = useState<Sponsor[]>([]);
  const [briefTopic, setBriefTopic] = useState<string | null>(null);
  const [briefLoading, setBriefLoading] = useState(false);

  async function openBrief(topic: string) {
    setBriefTopic(topic);
    setBrief(null);
    setSponsors([]);
    setBriefLoading(true);
    const jz = jurisdiction ? `&jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
    const t = encodeURIComponent(topic);
    try {
      // The briefing (LLM) and its leading sponsors (SQL) load in parallel.
      const [briefRes, sponsorRes] = await Promise.all([
        fetch(`${API_URL}/civic/insights/brief?topic=${t}${jz}`),
        fetch(`${API_URL}/civic/insights/sponsors?topic=${t}${jz}&limit=5`),
      ]);
      if (briefRes.ok) setBrief(await briefRes.json());
      if (sponsorRes.ok) setSponsors((await sponsorRes.json()).sponsors ?? []);
    } catch {
      /* leave brief null; the panel shows a gentle failure below */
    } finally {
      setBriefLoading(false);
    }
  }

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
    // A scope change invalidates any open briefing.
    setBrief(null);
    setSponsors([]);
    setBriefTopic(null);
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
            <p className="section-title">
              Legislative activity by topic{" "}
              <span className="hint">— click a topic for an advisory briefing</span>
            </p>
            <ul className="bars">
              {topics.map((t) => (
                <li key={t.topic}>
                  <button
                    type="button"
                    className={`bar-row bar-button${
                      briefTopic === t.topic ? " bar-active" : ""
                    }`}
                    onClick={() => openBrief(t.topic)}
                    disabled={briefLoading}
                  >
                    <span className="bar-label">{t.topic}</span>
                    <span className="bar-track">
                      <span
                        className="bar-fill"
                        style={{ width: `${maxBills ? (t.bills / maxBills) * 100 : 0}%` }}
                      />
                    </span>
                    <span className="bar-value">{t.bills}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}

        {briefTopic && (
          <div className="brief">
            <p className="section-title">
              Briefing: {briefTopic}
              {brief && !brief.refused ? ` · ${brief.matched_bills} matching bills` : ""}
            </p>
            {briefLoading && <p className="note">Analyzing legislation…</p>}
            {!briefLoading && !brief && (
              <p className="note status-err">Couldn&apos;t generate a briefing.</p>
            )}
            {!briefLoading && brief && (
              <>
                <p className={`answer${brief.refused ? " refusal" : ""}`}>
                  {brief.briefing}
                </p>
                {!brief.refused && brief.citations.length > 0 && (
                  <ul className="citations">
                    {brief.citations.map((c) => (
                      <li key={c.file_no}>
                        <span className="cite-id">#{c.file_no}</span> {c.title}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
            {!briefLoading && sponsors.length > 0 && (
              <div className="sponsors">
                <p className="section-title">Leading sponsors on this topic</p>
                <ul className="sponsor-list">
                  {sponsors.map((s) => (
                    <li key={s.name}>
                      <span className="sponsor-name">{s.name}</span>
                      <span className="sponsor-count">{s.bills} bills</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
