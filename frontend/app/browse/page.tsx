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

// One page of results; also the ?limit sent to the API so the short-page
// Next-disable check below is reliable (the API defaults to 50 otherwise).
const PAGE_SIZE = 20;

// Hard cap on a CSV export so a single request stays bounded (a few thousand
// rows) rather than paging the whole corpus. Sets past this are truncated and
// the UI notes it.
const EXPORT_LIMIT = 5000;

// Columns for the CSV export, in order.
const CSV_HEADER = ["file_no", "title", "status", "doc_type", "intro_date"];

// RFC 4180: quote a field if it contains a comma, double-quote, CR or LF, and
// escape embedded quotes by doubling them.
function csvField(v: string | null): string {
  let s = v == null ? "" : String(v);
  // A leading =, +, -, or @ can be run as a formula when the CSV is opened in a
  // spreadsheet; prefix those with an apostrophe to neutralize it.
  if (/^[=+\-@]/.test(s)) s = "'" + s;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function billsToCsv(rows: BillRow[]): string {
  const lines = [CSV_HEADER.join(",")];
  for (const b of rows) {
    lines.push(
      [b.file_no, b.title, b.status, b.doc_type, b.intro_date].map(csvField).join(",")
    );
  }
  return lines.join("\r\n");
}

// Dual-encoded status pill: color reinforces text, never replaces it.
// ENACTED/ADOPTED read as affirmative; FAILED/VETOED/PLACED ON FILE as terminal;
// everything else (in progress) stays muted.
function statusTokenClass(status: string | null): string {
  const s = (status ?? "").toUpperCase();
  if (s === "ENACTED" || s === "ADOPTED") return "status-token is-ok";
  if (s === "FAILED" || s === "VETOED" || s === "PLACED ON FILE")
    return "status-token is-danger";
  return "status-token";
}

export default function Browse() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [jurisdictions, setJurisdictions] = useState<Jurisdiction[]>([]);
  const [results, setResults] = useState<BillListResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Export state is kept separate from loading/error so an export run doesn't
  // disable the filter form or clobber the browse error, and vice versa.
  const [exporting, setExporting] = useState(false);
  const [exportNote, setExportNote] = useState<string | null>(null);

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

  // Load the first page of legislation on mount so the wide results column is
  // populated immediately instead of sitting blank until the user submits.
  // Reuses the existing fetch path (runQuery) with the default (empty) filters;
  // runs exactly once. eslint-disable is intentional — runQuery reads current
  // filters from closure and we only want the initial default load here.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    runQuery(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Shared by the filter form and the Prev/Next buttons. Reads the current
  // filters from closure and pages via an explicit offset so the buttons can
  // step without touching the filters. Offset is only committed on success.
  // Single source of truth for the active filters, so browse paging and CSV
  // export send byte-for-byte identical filter params.
  function buildFilterParams(): URLSearchParams {
    const p = new URLSearchParams();
    if (q.trim()) p.set("q", q.trim());
    if (status) p.set("status", status);
    if (jurisdiction) p.set("jurisdiction", jurisdiction);
    return p;
  }

  async function runQuery(nextOffset: number) {
    setLoading(true);
    setError(null);
    try {
      const params = buildFilterParams();
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(nextOffset));
      const res = await fetch(`${API_URL}/civic/bills?${params.toString()}`);
      if (!res.ok) {
        setError(
          `The Docket API returned ${res.status}. Is it running and ingested on :8000?`
        );
        return;
      }
      setResults((await res.json()) as BillListResponse);
      setOffset(nextOffset);
    } catch {
      setError(
        `Couldn't reach the Docket API at ${API_URL} — is it running on :8000?`
      );
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // A filter/search submit always resets to the first page.
    runQuery(0);
  }

  // Download the current filtered set (up to EXPORT_LIMIT rows) as CSV. Reuses
  // the exact active filters via buildFilterParams; builds the CSV client-side
  // and triggers a Blob download. Degrades to a subtle inline note on failure.
  async function exportCsv() {
    if (exporting) return;
    setExporting(true);
    setExportNote(null);
    try {
      const params = buildFilterParams();
      params.set("limit", String(EXPORT_LIMIT));
      params.set("offset", "0");
      const res = await fetch(`${API_URL}/civic/bills?${params.toString()}`);
      if (!res.ok) {
        setExportNote(`Export failed — the API returned ${res.status}.`);
        return;
      }
      const data = (await res.json()) as BillListResponse;
      if (typeof window === "undefined") return; // download only in the browser
      const csv = billsToCsv(data.bills);
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Docket-bills-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a); // required for Firefox
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      if (data.total > data.bills.length) {
        setExportNote(
          `Exported first ${data.bills.length.toLocaleString()} of ${data.total.toLocaleString()} matches (export is capped at ${EXPORT_LIMIT.toLocaleString()}).`
        );
      }
    } catch {
      setExportNote(
        `Couldn't reach the Docket API at ${API_URL} — is it running on :8000?`
      );
    } finally {
      setExporting(false);
    }
  }

  return (
    <main className="container-app">
      <header className="page-header">
        <p className="breadcrumb">
          <Link href="/">Docket</Link>
          <span className="sep">›</span>
          <span className="current">Browse</span>
        </p>
        <h1>Browse Philadelphia City Council legislation</h1>
        <p className="lede">
          Filter the corpus by title, status, or city. Select a bill for its
          timeline, sponsors, and roll-call.
        </p>
      </header>

      <div className="browse-grid">
        <aside className="browse-rail">
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

          {(q.trim() || status || jurisdiction) && (
            <div className="filter-chips">
              {q.trim() && (
                <button
                  type="button"
                  className="example-chip"
                  onClick={() => setQ("")}
                >
                  Title: “{q.trim()}” ×
                </button>
              )}
              {status && (
                <button
                  type="button"
                  className="example-chip"
                  onClick={() => setStatus("")}
                >
                  Status: {status} ×
                </button>
              )}
              {jurisdiction && (
                <button
                  type="button"
                  className="example-chip"
                  onClick={() => setJurisdiction("")}
                >
                  City: {jurisdiction} ×
                </button>
              )}
            </div>
          )}

          {results && (
            <div className="browse-actions">
              <button
                type="button"
                className="btn-secondary"
                onClick={exportCsv}
                disabled={exporting || results.bills.length === 0}
              >
                {exporting ? "Exporting…" : "Export CSV"}
              </button>
              {exportNote && <p className="note">{exportNote}</p>}
            </div>
          )}
        </aside>

        <div className="detail-main">
          {error && (
            <div className="error-state">
              <p className="error-state-msg" style={{ marginBottom: 0 }}>
                {error}
              </p>
            </div>
          )}

          {results && (
            <section>
              <div className="toolbar">
                <p className="note" style={{ fontVariantNumeric: "tabular-nums" }}>
                  {results.total.toLocaleString()} matching bill
                  {results.total === 1 ? "" : "s"}
                  {results.bills.length > 0
                    ? ` — showing ${offset + 1}-${offset + results.bills.length} of ${results.total.toLocaleString()}`
                    : ""}
                </p>
                <div className="row" style={{ marginTop: 0 }}>
                  <button
                    type="button"
                    onClick={() => runQuery(offset - PAGE_SIZE)}
                    disabled={loading || offset === 0}
                  >
                    Prev
                  </button>
                  <button
                    type="button"
                    onClick={() => runQuery(offset + PAGE_SIZE)}
                    disabled={loading || results.bills.length < PAGE_SIZE}
                  >
                    Next
                  </button>
                </div>
              </div>
              {results.bills.length === 0 ? (
                <div className="empty-state">
                  <p className="empty-state-title">No bills match these filters.</p>
                  <p className="empty-state-help">
                    Try loosening or clearing the filters to widen the search.
                  </p>
                  <div className="empty-state-actions">
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => {
                        setQ("");
                        setStatus("");
                        setJurisdiction("");
                      }}
                    >
                      Clear filters
                    </button>
                  </div>
                </div>
              ) : (
                <div className="data-list">
                  {results.bills.map((b, i) => (
                    <Link
                      key={b.file_no ?? `row-${i}`}
                      href={`/bill/${encodeURIComponent(b.file_no ?? "")}`}
                      className="data-row"
                    >
                      <span className="data-row-title">
                        #{b.file_no ?? "—"} · {b.title ?? "—"}
                      </span>
                      <span className="data-row-meta">
                        {b.doc_type ?? "—"} · {b.intro_date ?? "—"}{" "}
                        <span className={statusTokenClass(b.status)}>
                          {b.status ?? "—"}
                        </span>
                      </span>
                    </Link>
                  ))}
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </main>
  );
}
