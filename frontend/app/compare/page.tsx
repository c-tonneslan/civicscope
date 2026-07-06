"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Sparkline } from "../Trends";
import { PanelSkeleton } from "../Skeleton";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Mirrors app/civic/schemas.py: TopicsResponse / SponsorsResponse / TrendsResponse.
type TopicItem = { topic: string; bills: number };
type Sponsor = { name: string; bills: number };
type Trend = { topic: string; series: number[] };
type TrendsData = { years: number[]; topics: Trend[] };

// One comparison column: a topic's total bill count, its multi-year trend
// sparkline (when the corpus spans >= 2 years), and its top sponsors.
function CompareColumn({
  label,
  count,
  trends,
  sponsors,
}: {
  label: string;
  count: number | undefined;
  trends: TrendsData | null;
  sponsors: Sponsor[];
}) {
  const match = trends?.topics.find((x) => x.topic.toLowerCase() === label.toLowerCase());
  const series = match?.series;
  const showSpark = !!trends && trends.years.length >= 2 && !!series;
  const first = trends?.years[0];
  const last = trends ? trends.years[trends.years.length - 1] : undefined;

  return (
    <section className="panel compare-col">
      <p className="section-title">{label}</p>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          gap: "var(--space-5)",
          alignItems: "center",
          marginBottom: "var(--space-4)",
        }}
      >
        <div className="chip-stat">
          <span className="chip-stat-num">{count ?? "—"}</span>
          <span className="chip-stat-label">Total bills</span>
        </div>
        {showSpark && (
          <div className="trends">
            <div className="section-head">
              <p className="section-head-title">Activity over time</p>
              <p className="section-head-caption">
                {first}–{last} · bills per year
              </p>
            </div>
            <div className="chart-frame">
              <Sparkline series={series} />
            </div>
          </div>
        )}
      </div>

      <p className="section-title" style={{ marginTop: 16 }}>
        Top sponsors
      </p>
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
        <p className="note">No sponsors recorded.</p>
      )}
    </section>
  );
}

// Side-by-side comparison of two topics. Selection lives in the URL (?a=&b=)
// so a comparison is shareable; defaults to the two busiest topics.
function CompareView() {
  const sp = useSearchParams();
  const router = useRouter();
  const a = sp.get("a") ?? "";
  const b = sp.get("b") ?? "";

  const [topics, setTopics] = useState<TopicItem[]>([]);
  const [trends, setTrends] = useState<TrendsData | null>(null);
  const [sponsorsA, setSponsorsA] = useState<Sponsor[]>([]);
  const [sponsorsB, setSponsorsB] = useState<Sponsor[]>([]);
  const [loadingTopics, setLoadingTopics] = useState(true);
  const [failed, setFailed] = useState(false);

  // Topics (option list + counts) and trends load once.
  useEffect(() => {
    let live = true;
    setLoadingTopics(true);
    setFailed(false);
    // A non-OK response still RESOLVES the fetch, so throw to route the page to
    // a single failed state instead of parsing an error body.
    const getJson = async (path: string) => {
      const res = await fetch(`${API_URL}${path}`);
      if (!res.ok) throw new Error(`${path} -> ${res.status}`);
      return res.json();
    };
    Promise.all([getJson("/civic/insights/topics"), getJson("/civic/insights/trends")])
      .then(([t, tr]: [{ topics: TopicItem[] }, TrendsData]) => {
        if (!live) return;
        setTopics([...(t.topics ?? [])].sort((x, y) => y.bills - x.bills));
        setTrends(tr);
      })
      .catch(() => live && setFailed(true))
      .finally(() => live && setLoadingTopics(false));
    return () => {
      live = false;
    };
  }, []);

  // Once topics load, seed the two busiest topics into the URL — but only when
  // a/b are absent or don't match a real topic, so a shared/edited URL wins.
  useEffect(() => {
    if (topics.length < 2) return;
    const labels = new Set(topics.map((t) => t.topic));
    const aValid = a && labels.has(a);
    const bValid = b && labels.has(b);
    if (aValid && bValid) return;
    const nextA = aValid ? a : topics[0].topic;
    const nextB = bValid ? b : topics[1]?.topic ?? topics[0].topic;
    if (nextA === a && nextB === b) return;
    router.replace(
      `/compare?a=${encodeURIComponent(nextA)}&b=${encodeURIComponent(nextB)}`,
      { scroll: false },
    );
  }, [topics, a, b, router]);

  // Per-column sponsor fetches, split so changing one column leaves the other.
  useEffect(() => {
    if (!a) {
      setSponsorsA([]);
      return;
    }
    let live = true;
    fetch(`${API_URL}/civic/insights/sponsors?topic=${encodeURIComponent(a)}&limit=5`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((s: { sponsors: Sponsor[] }) => live && setSponsorsA(s.sponsors ?? []))
      .catch(() => live && setSponsorsA([]));
    return () => {
      live = false;
    };
  }, [a]);

  useEffect(() => {
    if (!b) {
      setSponsorsB([]);
      return;
    }
    let live = true;
    fetch(`${API_URL}/civic/insights/sponsors?topic=${encodeURIComponent(b)}&limit=5`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((s: { sponsors: Sponsor[] }) => live && setSponsorsB(s.sponsors ?? []))
      .catch(() => live && setSponsorsB([]));
    return () => {
      live = false;
    };
  }, [b]);

  // URL is the single source of truth: write the changed key, keep the other.
  const select = (key: "a" | "b", value: string) => {
    const params = new URLSearchParams();
    params.set("a", key === "a" ? value : a);
    params.set("b", key === "b" ? value : b);
    router.replace(`/compare?${params.toString()}`, { scroll: false });
  };

  const countFor = (label: string) => topics.find((t) => t.topic === label)?.bills;

  if (loadingTopics) {
    return (
      <main className="container-app">
        <div className="page-header">
          <p className="breadcrumb">
            <Link href="/">Docket</Link>
            <span className="sep">›</span>
            <span className="current">Compare</span>
          </p>
          <h1>Compare topics</h1>
        </div>
        <PanelSkeleton lines={5} label="Loading topics" />
      </main>
    );
  }

  if (failed || topics.length === 0) {
    return (
      <main className="container-app">
        <div className="page-header">
          <p className="breadcrumb">
            <Link href="/">Docket</Link>
            <span className="sep">›</span>
            <span className="current">Compare</span>
          </p>
          <h1>Compare topics</h1>
        </div>
        <p className="note">Comparison is unavailable right now. Try again shortly.</p>
        <p className="note" style={{ marginTop: 24 }}>
          <Link href="/">← Ask</Link>
        </p>
      </main>
    );
  }

  return (
    <main className="container-app">
      <div className="page-header">
        <p className="breadcrumb">
          <Link href="/">Docket</Link>
          <span className="sep">›</span>
          <span className="current">Compare</span>
        </p>
        <h1>Compare topics</h1>
        <p className="lede">
          Put two topics side by side — activity over time, total volume, and who's driving them.
        </p>
      </div>

      <div className="compare-shell">
        <aside className="compare-rail">
          <div className="compare-picker browse-filters">
            <div>
              <label htmlFor="compare-a">Topic A</label>
              <select
                id="compare-a"
                value={a}
                onChange={(e) => select("a", e.target.value)}
              >
                <option value="">Choose a topic…</option>
                {topics.map((t) => (
                  <option key={t.topic} value={t.topic}>
                    {t.topic}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="compare-b">Topic B</label>
              <select
                id="compare-b"
                value={b}
                onChange={(e) => select("b", e.target.value)}
              >
                <option value="">Choose a topic…</option>
                {topics.map((t) => (
                  <option key={t.topic} value={t.topic}>
                    {t.topic}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <p className="note" style={{ marginTop: 24 }}>
            <Link href="/">← Ask</Link>
          </p>
        </aside>

        <div className="detail-main">
          {a && b ? (
            <div className="compare-grid">
              <CompareColumn label={a} count={countFor(a)} trends={trends} sponsors={sponsorsA} />
              <CompareColumn label={b} count={countFor(b)} trends={trends} sponsors={sponsorsB} />
            </div>
          ) : (
            <section className="panel">
              <div className="empty-state">
                <p className="empty-state-title">Pick two topics to compare</p>
                <p className="empty-state-help">
                  Choose a topic in each column of the rail to put them side by side — total volume,
                  activity over time, and the members driving each one.
                </p>
              </div>

              <div className="compare-grid" style={{ marginTop: "var(--space-5)" }}>
                <div className="panel compare-col" aria-hidden>
                  <p className="section-title">Topic A</p>
                  <p className="note">
                    Total bills, a year-by-year activity sparkline, and the top five sponsors — ready
                    once you choose a topic.
                  </p>
                </div>
                <div className="panel compare-col" aria-hidden>
                  <p className="section-title">Topic B</p>
                  <p className="note">
                    The same breakdown for a second topic, laid out beside the first so the contrast
                    is easy to read.
                  </p>
                </div>
              </div>

              {topics.length > 0 && (
                <p className="note" style={{ marginTop: "var(--space-5)" }}>
                  Busiest right now: <strong>{topics[0].topic}</strong>
                  {topics[1] ? (
                    <>
                      {" "}
                      and <strong>{topics[1].topic}</strong>
                    </>
                  ) : null}
                  .
                </p>
              )}
            </section>
          )}
        </div>
      </div>
    </main>
  );
}

export default function ComparePage() {
  // useSearchParams / useRouter need a Suspense boundary in a client page for
  // the production build, so the data-fetching body lives in an inner component.
  return (
    <Suspense
      fallback={
        <main className="container-app">
          <div className="page-header">
            <p className="breadcrumb">
              <Link href="/">Docket</Link>
              <span className="sep">›</span>
              <span className="current">Compare</span>
            </p>
            <h1>Compare topics</h1>
          </div>
          <PanelSkeleton lines={5} label="Loading" />
        </main>
      }
    >
      <CompareView />
    </Suspense>
  );
}
