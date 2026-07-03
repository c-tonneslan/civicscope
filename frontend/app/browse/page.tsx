"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

// Base URL the browser uses to reach the FastAPI backend. Inlined at build
// time by Next because of the NEXT_PUBLIC_ prefix; falls back to the local
// backend port so the app works out of the box.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Shape of GET /civic/bills (see app/civic/schemas.py: BillListResponse).
type BillRow = {
  file_no: string | null;
  title: string | null;
  status: string | null;
  doc_type: string | null;
  intro_date: string | null;
};
type BillListResponse = {
  bills: BillRow[];
  total: number;
  limit: number;
  offset: number;
};
type Jurisdiction = { slug: string; documents: number };

// Statuses aren't enumerated by an endpoint, so this is a short curated list
// aligned with values seen in the corpus; "All" leaves the filter off.
const STATUSES = ["ADOPTED", "ENACTED", "IN COMMITTEE", "INTRODUCED", "PLACED ON FILE"];

export default function Browse() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [jurisdictions, setJurisdictions] = useState<Jurisdiction[]>([]);
  const [results, setResults] = useState<BillListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetch(`${API_URL}/civic/jurisdictions`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d: { jurisdictions: Jurisdiction[] }) => live && setJurisdictions(d.jurisdictions))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (q.trim()) params.set("q", q.trim());
      if (status) params.set("status", status);
      if (jurisdiction) params.set("jurisdiction", jurisdiction);
      const res = await fetch(`${API_URL}/civic/bills?${params.toString()}`);
      if (!res.ok) {
        setError(
          `The civicscope API returned ${res.status}. Is it running and ingested on :8000?`
        );
        return;
      }
      setResults((await res.json()) as BillListResponse);
    } catch {
      setError(
        `Couldn't reach the civicscope API at ${API_URL} — is it running on :8000?`
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="container">
      <p className="eyebrow">
        civicscope · Browse · <Link href="/">Ask</Link>
      </p>
      <h1>Browse Philadelphia City Council legislation</h1>
      <p className="lede">
        Filter the corpus by title, status, or city. Select a bill for its
        timeline, sponsors, and roll-call.
      </p>

      <div className="panel">
        <form onSubmit={onSubmit}>
          <div className="browse-filters">
            <div>
              <label htmlFor="q">Title contains</label>
              <input
                id="q"
                type="text"
                placeholder="zoning"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                disabled={loading}
              />
            </div>
            <div>
              <label htmlFor="status">Status</label>
              <select
                id="status"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                disabled={loading}
              >
                <option value="">All</option>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
            {jurisdictions.length > 1 && (
              <div>
                <label htmlFor="jurisdiction">City</label>
                <select
                  id="jurisdiction"
                  value={jurisdiction}
                  onChange={(e) => setJurisdiction(e.target.value)}
                  disabled={loading}
                >
                  <option value="">All cities</option>
                  {jurisdictions.map((j) => (
                    <option key={j.slug} value={j.slug}>
                      {j.slug} ({j.documents.toLocaleString()})
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
          <div className="row">
            <button type="submit" disabled={loading}>
              {loading ? "Loading…" : "Browse bills"}
            </button>
          </div>
        </form>
      </div>

      {error && (
        <p className="note status-err" style={{ marginTop: 24 }}>
          {error}
        </p>
      )}

      {results && (
        <section style={{ marginTop: 24 }}>
          <p className="note">
            {results.total.toLocaleString()} matching bill
            {results.total === 1 ? "" : "s"}
            {results.total > results.bills.length
              ? ` — showing ${results.bills.length}`
              : ""}
          </p>
          {results.bills.length === 0 ? (
            <p className="note">No bills match these filters.</p>
          ) : (
            results.bills.map((b, i) => (
              <Link
                key={b.file_no ?? `row-${i}`}
                href={`/bill/${encodeURIComponent(b.file_no ?? "")}`}
                className="bill-row"
              >
                <span className="bill-row-title">
                  #{b.file_no ?? "—"} · {b.title ?? "—"}
                </span>
                <span className="bill-row-meta">
                  {b.status ?? "—"} · {b.doc_type ?? "—"} · {b.intro_date ?? "—"}
                </span>
              </Link>
            ))
          )}
        </section>
      )}
    </main>
  );
}
