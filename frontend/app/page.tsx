"use client";

import { useEffect, useState } from "react";

import CitationList from "./CitationList";
import Digest from "./Digest";
import InsightsPanel from "./InsightsPanel";

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

export default function Home() {
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

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setStreamed("");
    try {
      const res = await fetch(`${API_URL}/civic/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          jurisdiction: jurisdiction || null,
        }),
      });
      if (!res.ok || !res.body) {
        setError(
          `The civicscope API returned ${res.status}. Is it running and ingested on :8000?`
        );
        return;
      }
      // Read the NDJSON stream: append token text live for perceived speed,
      // then overwrite `result` with the authoritative final event so the
      // existing refusal / answer / citation render block is reused verbatim.
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const handle = (line: string) => {
        const trimmed = line.trim();
        if (!trimmed) return;
        const ev = JSON.parse(trimmed) as StreamEvent;
        if (ev.type === "token") {
          setStreamed((prev) => prev + ev.text);
        } else {
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
      <p className="eyebrow">civicscope · Ask</p>
      <h1>Ask about Philadelphia City Council legislation</h1>
      <p className="lede">
        Answers are grounded in the real Philadelphia City Council records with
        citations, or civicscope refuses when the data doesn&apos;t support one.
      </p>

      <Digest jurisdiction={jurisdiction} />

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

        <form onSubmit={onSubmit}>
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
              {loading ? "Asking…" : "Ask civicscope"}
            </button>
          </div>
        </form>
      </div>

      {error && (
        <p className="note status-err" style={{ marginTop: 24 }}>
          {error}
        </p>
      )}

      {!result && loading && streamed && (
        <section style={{ marginTop: 24 }}>
          <div className="panel">
            <p className="answer">{streamed}</p>
          </div>
        </section>
      )}

      {result && (
        <section style={{ marginTop: 24 }}>
          <div className="panel">
            {result.refused ? (
              <p className="answer refusal">{result.answer}</p>
            ) : result.answer.trim() ? (
              <p className="answer">{result.answer}</p>
            ) : (
              <p className="answer refusal">No answer was produced.</p>
            )}

            {!result.refused && result.citations.length > 0 && (
              <>
                <p className="section-title">
                  Citations <span className="hint">— click a bill for its timeline</span>
                </p>
                <CitationList citations={result.citations} jurisdiction={jurisdiction} />
              </>
            )}

            {!result.refused && result.citations.length === 0 && (
              <p className="note">
                No citations were returned for this answer.
              </p>
            )}
          </div>
        </section>
      )}

      <InsightsPanel jurisdiction={jurisdiction} />
    </main>
  );
}
