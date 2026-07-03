"use client";

import { useState } from "react";

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

const EXAMPLES = [
  "What recent legislation concerns zoning?",
  "What legislation honors Philadelphia schools?",
  "Are there any bills about convenience fees?",
  "What legislation relates to affordable housing?",
];

export default function Home() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API_URL}/civic/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (!res.ok) {
        setError(
          `The civicscope API returned ${res.status}. Is it running and ingested on :8000?`
        );
        return;
      }
      const data: AskResponse = await res.json();
      setResult(data);
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

      <div className="panel">
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
                <p className="section-title">Citations</p>
                <ul className="citations">
                  {result.citations.map((c) => (
                    <li key={c.file_no}>
                      <span className="cite-id">#{c.file_no}</span> {c.title}
                    </li>
                  ))}
                </ul>
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
    </main>
  );
}
