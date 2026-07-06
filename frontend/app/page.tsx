"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";

import CitationList from "./CitationList";
import Digest from "./Digest";
import InsightsPanel from "./InsightsPanel";
import Watchlist from "./Watchlist";

// Base URL the browser uses to reach the FastAPI backend. Inlined at build
// time by Next because of the NEXT_PUBLIC_ prefix; falls back to the local
// backend port so the app works out of the box.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Shape of POST /civic/ask (see app/civic/schemas.py: AskResponse / Citation).
type Citation = { file_no: string; title: string };
type AskResponse = {
  answer: string;
  citations: Citation[];
  refused: boolean;
};

// NDJSON events from POST /civic/ask/stream (see app/civic/streaming.py).
// A token is a live answer fragment; the final event carries the authoritative
// verdict (citations + refused) — the UI renders trust only from it.
type StreamEvent =
  | { type: "token"; text: string }
  | { type: "final"; answer: string; citations: Citation[]; refused: boolean };

const EXAMPLES = [
  "What recent legislation concerns zoning?",
  "What legislation honors Philadelphia schools?",
  "Are there any bills about convenience fees?",
  "What legislation relates to affordable housing?",
];

type Jurisdiction = { slug: string; documents: number };

function HomeInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);
  // Answer text accumulated live from token events while the stream is open.
  // The final event overwrites `result`, so this is only shown mid-stream.
  const [streamed, setStreamed] = useState("");
  // "" means all cities; otherwise a Legistar client slug.
  const [jurisdiction, setJurisdiction] = useState("");
  const [jurisdictions, setJurisdictions] = useState<Jurisdiction[]>([]);

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

  const didInit = useRef(false);

  // Rewrite the URL query so the address bar reproduces the asked question.
  // Same route ('/'), query-only change → App Router does a shallow client
  // transition that keeps HomeInner mounted and the in-flight stream alive.
  function syncUrl(q: string, jz: string) {
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q);
    if (jz) params.set("jurisdiction", jz);
    const qs = params.toString();
    router.replace(qs ? `/?${qs}` : "/", { scroll: false });
  }

  // Core ask, parameterized so the mount-time auto-submit can pass URL-derived
  // values directly and avoid a stale-closure race with un-flushed state.
  async function runAsk(q: string, jz: string) {
    if (!q.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setStreamed("");
    try {
      const res = await fetch(`${API_URL}/civic/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          jurisdiction: jz || null,
        }),
      });
      if (!res.ok || !res.body) {
        setError(
          `The Docket API returned ${res.status}. Is it running and ingested on :8000?`
        );
        return;
      }
      // Read the NDJSON stream: append token text live for perceived speed,
      // then overwrite `result` with the authoritative final event so the
      // existing refusal / answer / citation render block is reused verbatim.
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      // The final event carries the authoritative verdict; track that it arrived
      // so a truncated stream (network/proxy cut mid-answer) surfaces an error
      // instead of silently leaving the draft text with no citations.
      let gotFinal = false;
      const handle = (line: string) => {
        const trimmed = line.trim();
        if (!trimmed) return;
        const ev = JSON.parse(trimmed) as StreamEvent;
        if (ev.type === "token") {
          setStreamed((prev) => prev + ev.text);
        } else {
          gotFinal = true;
          setResult({
            answer: ev.answer,
            citations: ev.citations,
            refused: ev.refused,
          });
        }
      };
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let nl = buffer.indexOf("\n");
        while (nl !== -1) {
          handle(buffer.slice(0, nl));
          buffer = buffer.slice(nl + 1);
          nl = buffer.indexOf("\n");
        }
      }
      // Flush a trailing partial line (the final event may arrive without a
      // trailing newline being read as a separate chunk).
      if (buffer) handle(buffer);
      if (!gotFinal) {
        setError("The answer stream ended before completing — please try again.");
      }
    } catch {
      setError(
        `Couldn't reach the Docket API at ${API_URL} — is it running on :8000?`
      );
    } finally {
      setLoading(false);
    }
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    syncUrl(question, jurisdiction);
    await runAsk(question, jurisdiction);
  }

  // One-shot: pre-fill + auto-submit from ?q= / ?jurisdiction= on first mount.
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    const urlQ = searchParams.get("q") ?? "";
    const urlJz = searchParams.get("jurisdiction") ?? "";
    if (urlJz) setJurisdiction(urlJz);
    if (urlQ.trim()) {
      setQuestion(urlQ);
      void runAsk(urlQ, urlJz);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once on mount only
  }, []);

  const totalDocuments = jurisdictions.reduce((sum, j) => sum + j.documents, 0);

  return (
    <main className="container-app">
      <div className="hero-split">
        <section className="hero">
        <p className="eyebrow">Docket</p>
        <h1>Answers about Philadelphia legislation you can actually cite.</h1>
        <p className="lede">
          Grounded, cited answers across years of Philadelphia City Council
          records — or an honest refusal when the data doesn&apos;t support one.
        </p>

        <div className="hero-stats">
          {jurisdictions.length > 0 && (
            <>
              <div className="hero-stat">
                <span className="hero-stat-num">{totalDocuments.toLocaleString()}</span>
                <span className="hero-stat-label">Bills indexed</span>
              </div>
              <div className="hero-stat">
                <span className="hero-stat-num">{jurisdictions.length.toLocaleString()}</span>
                <span className="hero-stat-label">
                  {jurisdictions.length === 1 ? "Jurisdiction" : "Jurisdictions"}
                </span>
              </div>
            </>
          )}
          <div className="hero-stat">
            <span className="hero-stat-num">2012–2026</span>
            <span className="hero-stat-label">Coverage</span>
          </div>
          <div className="hero-stat">
            <span className="hero-stat-num">Every answer</span>
            <span className="hero-stat-label">Cited</span>
          </div>
        </div>

        <div className="panel">
          {jurisdictions.length > 1 && (
            <div className="jz-row">
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

          <div className="examples">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                className="example-chip"
                onClick={() => setQuestion(ex)}
                disabled={loading}
              >
                {ex}
              </button>
            ))}
          </div>

          <form onSubmit={onSubmit} className="hero-input">
            <label htmlFor="question">Your question</label>
            <textarea
              id="question"
              rows={4}
              placeholder="What recent legislation concerns zoning?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={loading}
            />
            <div className="row">
              <button type="submit" disabled={loading || !question.trim()}>
                {loading ? "Asking…" : "Ask Docket"}
              </button>
              <Link href="/browse" className="btn-secondary">
                Browse all bills
              </Link>
            </div>
          </form>
        </div>

        {error && (
          <p className="note status-err" style={{ marginTop: 24 }}>
            {error}
          </p>
        )}

        {!result && loading && streamed && (
          <div className="response" style={{ marginTop: 24 }}>
            <p className="answer">{streamed}</p>
            <p className="note">Drafting — citations are verified when the answer completes.</p>
          </div>
        )}

        {result && (
          <div style={{ marginTop: 24 }}>
            {result.refused ? (
              <div className="refusal-card">
                <p className="refusal-eyebrow">No grounded answer</p>
                <p className="answer">{result.answer}</p>
                <div className="refusal-actions">
                  <button
                    type="button"
                    className="example-chip"
                    onClick={() => setQuestion(EXAMPLES[0])}
                    disabled={loading}
                  >
                    {EXAMPLES[0]}
                  </button>
                  <Link href="/browse" className="example-chip">
                    Browse all bills
                  </Link>
                </div>
              </div>
            ) : (
              <div className="response">
                {result.answer.trim() ? (
                  <>
                    <p className="answer">{result.answer}</p>
                    {result.citations.length > 0 ? (
                      <>
                        <span
                          className={
                            result.citations.length >= 3
                              ? "grounding-pill is-strong"
                              : "grounding-pill"
                          }
                        >
                          Grounded in {result.citations.length}{" "}
                          {result.citations.length === 1 ? "bill" : "bills"}
                        </span>
                        <p className="source-divider">Sources</p>
                        <CitationList citations={result.citations} jurisdiction={jurisdiction} />
                      </>
                    ) : (
                      <p className="note">No citations were returned for this answer.</p>
                    )}
                  </>
                ) : (
                  <p className="answer refusal">No answer was produced.</p>
                )}
              </div>
            )}
          </div>
        )}
          <div style={{ marginTop: 32 }}>
            <Watchlist jurisdiction={jurisdiction} />
          </div>
        </section>

        <aside className="hero-aside">
          <Digest jurisdiction={jurisdiction} />
        </aside>
      </div>

      <div style={{ marginTop: 48 }}>
        <InsightsPanel jurisdiction={jurisdiction} />
      </div>
    </main>
  );
}

export default function Home() {
  return (
    <Suspense fallback={null}>
      <HomeInner />
    </Suspense>
  );
}
