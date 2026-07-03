"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useState } from "react";

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

// A shareable per-bill page aggregating one Matter from the existing insight
// endpoints (timeline carries the header title/status/url; roll-call; sponsors).
function BillView({ fileNo }: { fileNo: string }) {
  const jurisdiction = useSearchParams().get("jurisdiction") ?? "";

  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [rollcall, setRollcall] = useState<RollCall | null>(null);
  const [sponsors, setSponsors] = useState<Sponsors | null>(null);
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

  if (loading) {
    return (
      <main className="container">
        <p className="eyebrow">civicscope · Bill</p>
        <p className="note">Loading bill…</p>
      </main>
    );
  }

  // A real bill with no history is still "found"; only a missing Matter (both
  // timeline and roll-call report not-found) is a 404 for the page.
  const missing = !timeline?.found && !rollcall?.found;
  if (missing) {
    return (
      <main className="container">
        <p className="eyebrow">civicscope · Bill</p>
        <h1>No bill found for #{fileNo}</h1>
        <p className="note">
          <Link href="/">← Ask</Link>
        </p>
      </main>
    );
  }

  const dissent = rollcall?.votes.filter((v) => v.vote && v.vote !== "Ayes") ?? [];

  return (
    <main className="container">
      <p className="eyebrow">civicscope · Bill</p>
      <h1>{timeline?.title ?? `#${fileNo}`}</h1>
      <p className="note">
        <span className="cite-id">#{fileNo}</span>
        {timeline?.status ? ` · ${timeline.status}` : ""}
        {timeline?.url ? (
          <>
            {" · "}
            <a href={timeline.url} target="_blank" rel="noopener noreferrer">
              Legistar record
            </a>
          </>
        ) : (
          ""
        )}
      </p>

      <div className="panel">
        <p className="section-title">Timeline</p>
        {timeline?.found && timeline.timeline.length > 0 ? (
          <ol className="timeline-list">
            {timeline.timeline.map((e, i) => (
              <li key={i}>
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

        <p className="section-title">Roll-call</p>
        {rollcall?.found && rollcall.votes.length > 0 ? (
          <p className="rollcall">
            <span className="rollcall-label">Roll-call:</span>{" "}
            {Object.entries(rollcall.tally)
              .map(([v, n]) => `${v} ${n}`)
              .join(" · ")}
            {dissent.length > 0 && (
              <span className="rollcall-dissent">
                {" "}
                — dissent:{" "}
                {dissent.map((v) => `${v.person} (${v.vote})`).join(", ")}
              </span>
            )}
          </p>
        ) : (
          <p className="note">No roll-call recorded for this bill yet.</p>
        )}

        <p className="section-title">Sponsors</p>
        {sponsors?.found && sponsors.sponsors.length > 0 ? (
          <ul className="sponsor-list">
            {sponsors.sponsors.map((s) => (
              <li key={`${s.name}-${s.seq ?? ""}`}>
                <span className="sponsor-name">{s.name}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="note">No sponsors recorded for this bill yet.</p>
        )}
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
        <main className="container">
          <p className="eyebrow">civicscope · Bill</p>
          <p className="note">Loading bill…</p>
        </main>
      }
    >
      <BillView fileNo={fileNo} />
    </Suspense>
  );
}
