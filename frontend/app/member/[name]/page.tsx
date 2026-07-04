"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useState } from "react";

// Base URL the browser uses to reach the FastAPI backend. Inlined at build
// time by Next because of the NEXT_PUBLIC_ prefix; falls back to the local
// backend port so the app works out of the box.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Bill = {
  file_no: string | null;
  title: string | null;
  status: string | null;
  doc_type: string | null;
  intro_date: string | null;
};
type Bills = { bills: Bill[]; total: number };
type RecordItem = { vote: string; bills: number };
type MemberRecord = { person: string; record: RecordItem[] };

// A lightweight topic tally derived client-side from sponsored-bill titles,
// keyed off the same TRACKED_TOPICS labels the backend uses (insights.py). This
// avoids a new endpoint; matching is substring/keyword only, so it's a hint.
const TOPIC_KEYWORDS: [string, string[]][] = [
  ["Housing", ["housing", "affordable", "rent", "eviction", "tenant", "landlord"]],
  ["Zoning & Land Use", ["zoning", "rezone", "overlay", "redevelopment", "subdivision"]],
  ["Transit & Streets", ["transit", "septa", "traffic", "parking", "bicycle", "pedestrian"]],
  ["Public Safety", ["police", "crime", "firearm", "gun", "violence", "safety"]],
  ["Education", ["school", "education", "student", "teacher", "scholarship"]],
  ["Budget & Taxes", ["budget", "tax", "appropriation", "fiscal", "levy", "revenue"]],
  ["Health", ["health", "hospital", "opioid", "medical", "mental"]],
  ["Environment", ["environment", "climate", "energy", "recycling", "stormwater"]],
  ["Jobs & Labor", ["worker", "wage", "employment", "labor", "union"]],
];

function topTopics(bills: Bill[]): { topic: string; bills: number }[] {
  const counts = new Map<string, number>();
  for (const b of bills) {
    const t = (b.title ?? "").toLowerCase();
    for (const [label, words] of TOPIC_KEYWORDS) {
      if (words.some((w) => t.includes(w))) {
        counts.set(label, (counts.get(label) ?? 0) + 1);
      }
    }
  }
  return [...counts.entries()]
    .map(([topic, n]) => ({ topic, bills: n }))
    .sort((a, b) => b.bills - a.bills)
    .slice(0, 5);
}

// A shareable per-member hub aggregating the Matters a council member sponsored
// (via the /civic/bills ?sponsor= filter), their roll-call record (/insights/
// member), and a client-derived breakdown of their most-active topics.
function MemberView({ name }: { name: string }) {
  const jurisdiction = useSearchParams().get("jurisdiction") ?? "";

  const [bills, setBills] = useState<Bills | null>(null);
  const [record, setRecord] = useState<MemberRecord | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    const jz = jurisdiction ? `&jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
    const p = encodeURIComponent(name);
    // Any non-OK response still RESOLVES the fetch, so throw on it to route the
    // page to .catch (which renders not-found) instead of parsing an error body.
    const getJson = async (path: string) => {
      const res = await fetch(`${API_URL}${path}`);
      if (!res.ok) throw new Error(`${path} -> ${res.status}`);
      return res.json();
    };
    Promise.all([
      getJson(`/civic/bills?sponsor=${p}&limit=100${jz}`),
      getJson(`/civic/insights/member?person=${p}${jz}`),
    ])
      .then(([b, r]: [Bills, MemberRecord]) => {
        if (!live) return;
        setBills(b);
        setRecord(r);
      })
      .catch(() => {
        if (!live) return;
        setBills(null);
        setRecord(null);
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [name, jurisdiction]);

  if (loading) {
    return (
      <main className="container">
        <p className="eyebrow">civicscope · Member</p>
        <p className="note">Loading member…</p>
      </main>
    );
  }

  const sponsored = bills?.bills ?? [];
  const votes = record?.record ?? [];
  // Nothing on either surface -> the member is absent from the corpus.
  const missing = sponsored.length === 0 && votes.length === 0;
  if (missing) {
    return (
      <main className="container">
        <p className="eyebrow">civicscope · Member</p>
        <h1>No record found for {name}</h1>
        <p className="note">
          <Link href="/">← Ask</Link>
        </p>
      </main>
    );
  }

  const topics = topTopics(sponsored);
  const jzQuery = jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : "";

  return (
    <main className="container">
      <p className="eyebrow">civicscope · Member</p>
      <h1>{name}</h1>
      <p className="note">
        <span className="cite-id">{sponsored.length} sponsored</span>
        {votes.length > 0 ? ` · ${votes.reduce((n, v) => n + v.bills, 0)} recorded votes` : ""}
      </p>

      <div className="panel">
        <p className="section-title">Sponsored bills</p>
        {sponsored.length > 0 ? (
          <ul className="citations">
            {sponsored.map((b) => (
              <li key={b.file_no ?? b.title}>
                <div className="cite-button">
                  {b.file_no ? (
                    <Link
                      className="cite-id"
                      href={`/bill/${encodeURIComponent(b.file_no)}${jzQuery}`}
                    >
                      #{b.file_no}
                    </Link>
                  ) : (
                    <span className="cite-id">—</span>
                  )}
                  <span className="cite-title">
                    {b.title ?? "Untitled"}
                    {b.status ? ` · ${b.status}` : ""}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="note">No sponsored bills on record for this member.</p>
        )}

        <p className="section-title">Vote record</p>
        {votes.length > 0 ? (
          <p className="rollcall">
            {votes.map((v) => `${v.vote} ${v.bills}`).join(" · ")}
          </p>
        ) : (
          <p className="note">No roll-call votes on record for this member.</p>
        )}

        {topics.length > 0 && (
          <>
            <p className="section-title">Most-active topics</p>
            <ul className="sponsor-list">
              {topics.map((t) => (
                <li key={t.topic}>
                  <span className="sponsor-name">{t.topic}</span>
                  <span className="sponsor-count">{t.bills} bills</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      <p className="note" style={{ marginTop: 24 }}>
        <Link href="/">← Ask</Link>
      </p>
    </main>
  );
}

export default function MemberPage({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name } = use(params);
  // Member names carry spaces/periods and arrive URL-encoded; a malformed value
  // (stray %) would throw, so fall back to the raw segment rather than crash.
  let memberName = name;
  try {
    memberName = decodeURIComponent(name);
  } catch {
    memberName = name;
  }
  // useSearchParams needs a Suspense boundary in a client page for the
  // production build, so the data-fetching body lives in an inner component.
  return (
    <Suspense
      fallback={
        <main className="container">
          <p className="eyebrow">civicscope · Member</p>
          <p className="note">Loading member…</p>
        </main>
      }
    >
      <MemberView name={memberName} />
    </Suspense>
  );
}
