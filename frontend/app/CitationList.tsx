"use client";

import Link from "next/link";
import { useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Citation = { file_no: string; title: string };
type TimelineEntry = {
  action_date: string | null;
  action: string | null;
  passed: string | null;
};
type Timeline = {
  found: boolean;
  status: string | null;
  url: string | null;
  timeline: TimelineEntry[];
};
type RollCall = {
  found: boolean;
  tally: Record<string, number>;
  votes: { person: string; vote: string | null }[];
};

// A citation list where clicking a bill expands its legislative timeline
// (GET /civic/insights/timeline). Used for both /ask answers and topic briefs.
export default function CitationList({
  citations,
  jurisdiction = "",
}: {
  citations: Citation[];
  jurisdiction?: string;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [data, setData] = useState<Timeline | null>(null);
  const [rollcall, setRollcall] = useState<RollCall | null>(null);
  const [loading, setLoading] = useState(false);

  async function toggle(fileNo: string) {
    if (open === fileNo) {
      setOpen(null);
      return;
    }
    setOpen(fileNo);
    setData(null);
    setRollcall(null);
    setLoading(true);
    const jz = jurisdiction ? `&jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
    const f = encodeURIComponent(fileNo);
    try {
      const [tRes, rRes] = await Promise.all([
        fetch(`${API_URL}/civic/insights/timeline?file_no=${f}${jz}`),
        fetch(`${API_URL}/civic/insights/rollcall?file_no=${f}${jz}`),
      ]);
      if (tRes.ok) setData(await tRes.json());
      if (rRes.ok) setRollcall(await rRes.json());
    } catch {
      /* leave data null; the row shows a gentle "no timeline" note */
    } finally {
      setLoading(false);
    }
  }

  return (
    <ul className="citations">
      {citations.map((c) => (
        <li key={c.file_no}>
          <div className="cite-button">
            <Link
              className="cite-id"
              href={`/bill/${encodeURIComponent(c.file_no)}${
                jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : ""
              }`}
            >
              #{c.file_no}
            </Link>
            <button type="button" className="cite-open" onClick={() => toggle(c.file_no)}>
              <span className="cite-title">{c.title}</span>
              <span className="cite-toggle">{open === c.file_no ? "hide" : "timeline"}</span>
            </button>
          </div>
          {open === c.file_no && (
            <div className="timeline">
              {loading && <p className="note">Loading timeline…</p>}
              {!loading && data?.found && data.timeline.length > 0 && (
                <ol className="timeline-list">
                  {data.timeline.map((e, i) => (
                    <li key={i}>
                      <span className="tl-date">{e.action_date ?? "—"}</span>
                      <span className="tl-action">
                        {e.action}
                        {e.passed ? ` · ${e.passed}` : ""}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
              {!loading && (!data?.found || data.timeline.length === 0) && (
                <p className="note">No timeline recorded for this bill yet.</p>
              )}
              {!loading && rollcall?.found && rollcall.votes.length > 0 && (
                <p className="rollcall">
                  <span className="rollcall-label">Roll-call:</span>{" "}
                  {Object.entries(rollcall.tally)
                    .map(([v, n]) => `${v} ${n}`)
                    .join(" · ")}
                  {rollcall.votes.some((v) => v.vote && v.vote !== "Ayes") && (
                    <span className="rollcall-dissent">
                      {" "}
                      — dissent:{" "}
                      {rollcall.votes
                        .filter((v) => v.vote && v.vote !== "Ayes")
                        .map((v) => `${v.person} (${v.vote})`)
                        .join(", ")}
                    </span>
                  )}
                </p>
              )}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
