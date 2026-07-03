"use client";

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
  const [loading, setLoading] = useState(false);

  async function toggle(fileNo: string) {
    if (open === fileNo) {
      setOpen(null);
      return;
    }
    setOpen(fileNo);
    setData(null);
    setLoading(true);
    const jz = jurisdiction ? `&jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
    try {
      const res = await fetch(
        `${API_URL}/civic/insights/timeline?file_no=${encodeURIComponent(fileNo)}${jz}`
      );
      if (res.ok) setData(await res.json());
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
          <button type="button" className="cite-button" onClick={() => toggle(c.file_no)}>
            <span className="cite-id">#{c.file_no}</span>
            <span className="cite-title">{c.title}</span>
            <span className="cite-toggle">{open === c.file_no ? "hide" : "timeline"}</span>
          </button>
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
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
