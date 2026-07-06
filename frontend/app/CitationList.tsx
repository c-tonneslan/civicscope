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
      {citations.map((c, i) => (
        <li key={c.file_no} style={{ overflow: "hidden" }}>
          <div className="cite-button" style={{ minWidth: 0 }}>
            <span
              className="cite-id"
              aria-hidden="true"
              style={{ flex: "none", opacity: 0.7 }}
            >
              [{i + 1}]
            </span>
            <Link
              className="cite-id"
              style={{ flex: "none" }}
              href={`/bill/${encodeURIComponent(c.file_no)}${
                jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : ""
              }`}
            >
              #{c.file_no}
            </Link>
            <button
              type="button"
              className="cite-open"
              onClick={() => toggle(c.file_no)}
              style={{ minWidth: 0 }}
            >
              <span
                className="cite-title"
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {c.title}
              </span>
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
                <div className="vote-tally">
                  {(() => {
                    const entries = Object.entries(rollcall.tally);
                    const total = entries.reduce((sum, [, n]) => sum + n, 0);
                    const segClass = (v: string) => {
                      const k = v.toLowerCase();
                      if (k.startsWith("aye") || k.startsWith("yea")) return "yea";
                      if (k.startsWith("nay") || k.startsWith("no")) return "nay";
                      return "abstain";
                    };
                    return (
                      <>
                        <span className="rollcall-label">Roll-call</span>
                        {total > 0 && (
                          <div className="vote-bar" style={{ marginTop: 6 }}>
                            {entries.map(([v, n]) => (
                              <span
                                key={v}
                                className={`vote-seg ${segClass(v)}`}
                                style={{ width: `${(n / total) * 100}%` }}
                              />
                            ))}
                          </div>
                        )}
                        <div className="vote-legend">
                          {entries.map(([v, n]) => (
                            <span key={v}>
                              {v} {n}
                            </span>
                          ))}
                        </div>
                      </>
                    );
                  })()}
                  {rollcall.votes.some((v) => v.vote && v.vote !== "Ayes") && (
                    <div className="vote-dissent">
                      {rollcall.votes
                        .filter((v) => v.vote && v.vote !== "Ayes")
                        .map((v, i) => (
                          <Link
                            key={`${v.person}-${i}`}
                            className="member-chip"
                            href={`/member/${encodeURIComponent(v.person)}`}
                          >
                            {v.person}
                            <span className="sponsor-count">({v.vote})</span>
                          </Link>
                        ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
