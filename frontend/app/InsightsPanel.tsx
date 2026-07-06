"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import CitationList from "./CitationList";
import Trends from "./Trends";

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
type Velocity = { enacted: number; avg_days_to_enact: number | null };

export default function InsightsPanel({ jurisdiction = "" }: { jurisdiction?: string }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [topics, setTopics] = useState<TopicItem[] | null>(null);
  const [velocity, setVelocity] = useState<Velocity | null>(null);
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
      getJson(`/civic/insights/velocity${qs}`),
    ])
      .then(([o, t, v]: [Overview, Topics, Velocity]) => {
        if (!live) return;
        setOverview(o);
        setTopics(t.topics);
        setVelocity(v);
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
      <p className="eyebrow">Docket · Insights</p>
      <div className="panel">
        {overview && typeof overview.total_documents === "number" && (
          <div className="kpi-grid">
            <div className="kpi">
              <span className="kpi-label">Bills &amp; resolutions</span>
              <span className="kpi-num">{overview.total_documents.toLocaleString()}</span>
            </div>
            {overview.earliest_intro_date && overview.latest_intro_date && (
              <div className="kpi">
                <span className="kpi-label">Introduced-date span</span>
                <span className="kpi-num" style={{ fontSize: "1.15rem" }}>
                  {overview.earliest_intro_date} → {overview.latest_intro_date}
                </span>
              </div>
            )}
            <div className="kpi">
              <span className="kpi-label">Top statuses</span>
              <span className="kpi-num" style={{ fontSize: "1.05rem", lineHeight: 1.3 }}>
                {overview.by_status.slice(0, 3).map((s) => `${s.label} ${s.count}`).join(" · ")}
              </span>
            </div>
            {velocity && velocity.avg_days_to_enact != null && (
              <div className="kpi">
                <span className="kpi-label">Avg time to enact</span>
                <span className="kpi-num">~{velocity.avg_days_to_enact} days</span>
                <span className="kpi-context">
                  {velocity.enacted.toLocaleString()} enacted
                </span>
              </div>
            )}
          </div>
        )}

        {topics && topics.length > 0 && (
          <>
            <div className="section-head">
              <p className="section-head-title">Legislative activity by topic</p>
              <p className="section-head-caption">
                Click a topic for an advisory briefing
              </p>
            </div>
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
                  <Link
                    className="hint"
                    href={`/topic/${encodeURIComponent(t.topic)}${
                      jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : ""
                    }`}
                  >
                    ↗ page
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}

        <Trends jurisdiction={jurisdiction} />

        {briefTopic && (
          <div className="brief">
            <div className="section-head">
              <p className="section-head-title">Briefing: {briefTopic}</p>
              {brief && !brief.refused && (
                <p className="section-head-caption">
                  {brief.matched_bills} matching bills
                </p>
              )}
            </div>
            {briefLoading && <p className="note">Analyzing legislation…</p>}
            {!briefLoading && !brief && (
              <p className="note status-err">Couldn&apos;t generate a briefing.</p>
            )}
            {!briefLoading && brief && (
              <div className={brief.refused ? undefined : "response"}>
                <p className={`answer${brief.refused ? " refusal" : ""}`}>
                  {brief.briefing}
                </p>
                {!brief.refused && brief.citations.length > 0 && (
                  <>
                    <p className="source-divider">Sources</p>
                    <CitationList citations={brief.citations} jurisdiction={jurisdiction} />
                  </>
                )}
              </div>
            )}
            {!briefLoading && sponsors.length > 0 && (
              <div className="sponsors">
                <p className="section-title">Leading sponsors on this topic</p>
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
          </div>
        )}
      </div>
    </section>
  );
}
