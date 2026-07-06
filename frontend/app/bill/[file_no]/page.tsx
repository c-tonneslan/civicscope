"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useState } from "react";

import { PanelSkeleton } from "../../Skeleton";

// Base URL the browser uses to reach the FastAPI backend. Inlined at build
// time by Next because of the NEXT_PUBLIC_ prefix; falls back to the local
// backend port so the app works out of the box.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type TimelineEntry = {
  action_date: string | null;
  action: string | null;
  passed: string | null;
};
type Timeline = {
  found: boolean;
  title: string | null;
  status: string | null;
  url: string | null;
  timeline: TimelineEntry[];
};
type RollCall = {
  found: boolean;
  action: string | null;
  action_date: string | null;
  tally: Record<string, number>;
  votes: { person: string; vote: string | null }[];
};
type BillSponsor = { name: string; seq: number | null };
type Sponsors = { found: boolean; sponsors: BillSponsor[] };
type BillRow = {
  file_no: string | null;
  title: string | null;
  status: string | null;
  doc_type: string | null;
  intro_date: string | null;
};
type BillList = { bills: BillRow[]; total: number; limit: number; offset: number };

// A shareable per-bill page aggregating one Matter from the existing insight
// endpoints (timeline carries the header title/status/url; roll-call; sponsors).
function BillView({ fileNo }: { fileNo: string }) {
  const jurisdiction = useSearchParams().get("jurisdiction") ?? "";

  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [rollcall, setRollcall] = useState<RollCall | null>(null);
  const [sponsors, setSponsors] = useState<Sponsors | null>(null);
  const [more, setMore] = useState<{ sponsor: string; bills: BillRow[] } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    const jz = jurisdiction ? `&jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
    const f = encodeURIComponent(fileNo);
    // Any non-OK response still RESOLVES the fetch, so throw on it to route the
    // page to .catch (which renders not-found) instead of parsing an error body.
    const getJson = async (path: string) => {
      const res = await fetch(`${API_URL}${path}`);
      if (!res.ok) throw new Error(`${path} -> ${res.status}`);
      return res.json();
    };
    Promise.all([
      getJson(`/civic/insights/timeline?file_no=${f}${jz}`),
      getJson(`/civic/insights/rollcall?file_no=${f}${jz}`),
      getJson(`/civic/insights/bill-sponsors?file_no=${f}${jz}`),
    ])
      .then(([t, r, s]: [Timeline, RollCall, Sponsors]) => {
        if (!live) return;
        setTimeline(t);
        setRollcall(r);
        setSponsors(s);
      })
      .catch(() => {
        if (!live) return;
        setTimeline(null);
        setRollcall(null);
        setSponsors(null);
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [fileNo, jurisdiction]);

  // Primary sponsor drives the "More from this sponsor" section: prefer seq 0,
  // else the first entry so a bill whose sponsors all have null seq still picks one.
  const primary =
    sponsors?.found && sponsors.sponsors.length > 0
      ? (sponsors.sponsors.find((s) => s.seq === 0) ?? sponsors.sponsors[0])
      : null;

  // Separate from the core-load gate so a slow/failed related fetch never blocks
  // or errors the page; degrades to nothing when there's no sponsor or on failure.
  useEffect(() => {
    let live = true;
    if (!primary?.name) {
      setMore(null);
      return () => {
        live = false;
      };
    }
    const params = new URLSearchParams({ sponsor: primary.name, limit: "8" });
    if (jurisdiction) params.set("jurisdiction", jurisdiction);
    (async () => {
      try {
        const res = await fetch(`${API_URL}/civic/bills?${params.toString()}`);
        if (!res.ok) {
          if (live) setMore(null);
          return;
        }
        const data: BillList = await res.json();
        const rows = (data.bills ?? [])
          .filter((b) => b.file_no && b.file_no !== fileNo)
          .slice(0, 6);
        if (!live) return;
        setMore(rows.length > 0 ? { sponsor: primary.name, bills: rows } : null);
      } catch {
        if (live) setMore(null);
      }
    })();
    return () => {
      live = false;
    };
  }, [primary?.name, fileNo, jurisdiction]);

  if (loading) {
    return (
      <main className="container-wide">
        <p className="eyebrow">Docket · Bill</p>
        <PanelSkeleton lines={6} label="Loading bill" />
      </main>
    );
  }

  // A real bill with no history is still "found"; only a missing Matter (both
  // timeline and roll-call report not-found) is a 404 for the page.
  const missing = !timeline?.found && !rollcall?.found;
  if (missing) {
    return (
      <main className="container-wide">
        <div className="empty-state">
          <p className="empty-state-title">No bill found for #{fileNo}</p>
          <p className="empty-state-help">
            We couldn&apos;t match this file number to a Matter in the record.
          </p>
          <div className="empty-state-actions">
            <Link className="btn-secondary" href="/">
              Ask a question
            </Link>
            <Link className="btn-secondary" href="/browse">
              Browse bills
            </Link>
          </div>
        </div>
      </main>
    );
  }

  const dissent = rollcall?.votes.filter((v) => v.vote && v.vote !== "Ayes") ?? [];

  // Dual-encoded status pill: text is always present, color reinforces it.
  const statusTokenClass = (status: string | null): string => {
    const s = (status ?? "").toUpperCase();
    if (s.includes("ENACTED") || s.includes("ADOPTED")) return "status-token is-ok";
    if (s.includes("FAILED") || s.includes("VETOED") || s.includes("PLACED ON FILE"))
      return "status-token is-danger";
    return "status-token";
  };

  // Map a tally key name to a vote segment lane (position + text, not color alone).
  const voteSegClass = (key: string): string => {
    const k = key.toLowerCase();
    if (k.includes("aye") || k.includes("yea")) return "vote-seg yea";
    if (k.includes("nay") || k.includes("no")) return "vote-seg nay";
    return "vote-seg abstain";
  };

  const tallyEntries = rollcall?.found ? Object.entries(rollcall.tally ?? {}) : [];
  const tallyTotal = tallyEntries.reduce((sum, [, n]) => sum + n, 0);

  return (
    <main className="container-wide">
      <header className="entity-header page-header">
        <nav className="breadcrumb">
          <Link href="/">Docket</Link>
          <span className="sep">›</span>
          <Link href="/browse">Bill</Link>
          <span className="sep">›</span>
          <span className="current">#{fileNo}</span>
        </nav>
        <h1>{timeline?.title ?? `#${fileNo}`}</h1>
        <div className="page-header-meta">
          {timeline?.status ? (
            <span className={statusTokenClass(timeline.status)}>{timeline.status}</span>
          ) : null}
          {timeline?.url ? (
            <a
              className="page-header-actions"
              href={timeline.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Legistar record ↗
            </a>
          ) : null}
        </div>
      </header>

      <div className="detail-grid">
        <div className="detail-main">
          <div className="detail-modules">
            <div className="panel">
              <p className="section-title">Timeline</p>
              {timeline?.found && timeline.timeline.length > 0 ? (
                <ol className="timeline-rail">
                  {timeline.timeline.map((e, i) => (
                    <li
                      key={i}
                      className={i === timeline.timeline.length - 1 ? "is-current" : undefined}
                    >
                      <span className="tl-date">{e.action_date ?? "—"}</span>
                      <span className="tl-action">
                        {e.action}
                        {e.passed ? ` · ${e.passed}` : ""}
                      </span>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="note">No timeline recorded for this bill yet.</p>
              )}
            </div>

            <div className="panel">
              <p className="section-title">Roll-call</p>
              {rollcall?.found && rollcall.votes.length > 0 ? (
                <div className="vote-tally">
                  <div className="vote-bar">
                    {tallyEntries.map(([key, n]) => (
                      <span
                        key={key}
                        className={voteSegClass(key)}
                        style={{ width: tallyTotal > 0 ? `${(n / tallyTotal) * 100}%` : "0%" }}
                      />
                    ))}
                  </div>
                  <div className="vote-legend">
                    {tallyEntries.map(([key, n]) => (
                      <span key={key}>
                        {key} {n}
                      </span>
                    ))}
                  </div>
                  {dissent.length > 0 && (
                    <div className="vote-dissent">
                      {dissent.map((v, i) => (
                        <Link
                          key={`${v.person}-${i}`}
                          className="member-chip"
                          href={`/member/${encodeURIComponent(v.person)}`}
                        >
                          {v.person} <span className="tl-date">({v.vote})</span>
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <p className="note">No roll-call recorded for this bill yet.</p>
              )}
            </div>
          </div>

          {more && more.bills.length > 0 && (
            <div className="panel" style={{ marginTop: "var(--space-5)" }}>
              <p className="section-title">
                More from{" "}
                <Link
                  className="sponsor-name"
                  href={`/member/${encodeURIComponent(more.sponsor)}`}
                >
                  {more.sponsor}
                </Link>
              </p>
              <div className="data-list">
                {more.bills.map((b, i) => (
                  <Link
                    key={b.file_no ?? `m-${i}`}
                    className="data-row"
                    href={`/bill/${encodeURIComponent(b.file_no ?? "")}${
                      jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : ""
                    }`}
                  >
                    <span className="data-row-title">
                      #{b.file_no ?? "—"} · {b.title ?? "—"}
                    </span>
                    <span className="data-row-meta">
                      {b.status ?? "—"} · {b.intro_date ?? "—"}
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          )}
        </div>

        <aside className="detail-side">
          <div className="panel">
            <p className="section-title">Sponsors</p>
            {sponsors?.found && sponsors.sponsors.length > 0 ? (
              <ul className="sponsor-list">
                {sponsors.sponsors.map((s) => (
                  <li key={`${s.name}-${s.seq ?? ""}`}>
                    <Link
                      className="sponsor-name"
                      href={`/member/${encodeURIComponent(s.name)}`}
                    >
                      {s.name}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="note">No sponsors recorded for this bill yet.</p>
            )}
          </div>
        </aside>
      </div>

      <p className="note" style={{ marginTop: 24 }}>
        <Link href="/">← Ask</Link>
      </p>
    </main>
  );
}

export default function BillPage({
  params,
}: {
  params: Promise<{ file_no: string }>;
}) {
  const { file_no } = use(params);
  const fileNo = decodeURIComponent(file_no);
  // useSearchParams needs a Suspense boundary in a client page for the
  // production build, so the data-fetching body lives in an inner component.
  return (
    <Suspense
      fallback={
        <main className="container-wide">
          <p className="eyebrow">Docket · Bill</p>
          <PanelSkeleton lines={6} label="Loading bill" />
        </main>
      }
    >
      <BillView fileNo={fileNo} />
    </Suspense>
  );
}
