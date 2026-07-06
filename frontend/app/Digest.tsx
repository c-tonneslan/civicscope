"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Mirrors app/civic/schemas.py: DigestItem / RecentActivityResponse.
type DigestItem = {
  file_no: string | null;
  title: string | null;
  status: string | null;
  intro_date: string | null;
  last_action_date: string | null;
};
type Recent = { introduced: DigestItem[]; enacted: DigestItem[] };

export default function Digest({ jurisdiction = "" }: { jurisdiction?: string }) {
  const [introduced, setIntroduced] = useState<DigestItem[]>([]);
  const [enacted, setEnacted] = useState<DigestItem[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setFailed(false);
    const qs = jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
    // A non-OK response (e.g. a 404 from an un-restarted backend) still resolves
    // the fetch; throw so .catch hides the section instead of rendering undefined.
    const getJson = async (path: string) => {
      const res = await fetch(`${API_URL}${path}`);
      if (!res.ok) throw new Error(`${path} -> ${res.status}`);
      return res.json();
    };
    getJson(`/civic/insights/recent${qs}`)
      .then((r: Recent) => {
        if (!live) return;
        setIntroduced(r.introduced);
        setEnacted(r.enacted);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [jurisdiction]);

  // Bonus value: stay quiet on failure or when nothing moved, so a backend that
  // isn't up (or has no recent activity) never breaks the Ask experience.
  if (failed || (!introduced.length && !enacted.length)) return null;

  const rows = (items: DigestItem[], enactedList: boolean) => (
    <ul className="citations">
      {items
        .filter((it) => it.file_no)
        .map((it) => {
          const when = enactedList ? it.last_action_date : it.intro_date;
          return (
            <li key={it.file_no}>
              <div className="cite-button">
                <Link
                  className="cite-id"
                  href={`/bill/${encodeURIComponent(it.file_no as string)}${
                    jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : ""
                  }`}
                >
                  #{it.file_no}
                </Link>
                <span className="cite-title">
                  {it.title}
                  {when ? ` · ${when}` : ""}
                </span>
              </div>
            </li>
          );
        })}
    </ul>
  );

  return (
    <section className="digest" style={{ marginTop: 24 }}>
      <p className="eyebrow">civicscope · What&apos;s new</p>
      <div className="panel">
        {introduced.length > 0 && (
          <>
            <p className="section-title">Recently introduced</p>
            {rows(introduced, false)}
          </>
        )}
        {enacted.length > 0 && (
          <>
            <p className="section-title">Recently enacted</p>
            {rows(enacted, true)}
          </>
        )}
      </div>
    </section>
  );
}
