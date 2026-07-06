"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// User-owned, browser-persisted list of topics. Stable, namespaced key so a
// future rename doesn't silently orphan someone's watchlist.
const STORAGE_KEY = "civicscope.watchlist.topics";

// Curated quick-add labels mirroring TRACKED_TOPICS in app/civic/insights.py.
// Hardcoded (like EXAMPLES in page.tsx) — the frontend can't import Python.
const QUICK_TOPICS = [
  "Housing",
  "Zoning & Land Use",
  "Transit & Streets",
  "Public Safety",
  "Education",
  "Budget & Taxes",
  "Health",
  "Environment",
  "Jobs & Labor",
];

// Mirrors app/civic/schemas.py: BillListItem (the subset we render).
type WatchItem = {
  file_no: string | null;
  title: string | null;
  status: string | null;
  intro_date: string | null;
};

export default function Watchlist({ jurisdiction = "" }: { jurisdiction?: string }) {
  const [topics, setTopics] = useState<string[]>([]);
  // Gates the localStorage write and the empty-state render: never touch
  // storage or diverge from the server-rendered HTML until the client read ran.
  const [hydrated, setHydrated] = useState(false);
  const [input, setInput] = useState("");
  const [byTopic, setByTopic] = useState<Record<string, WatchItem[]>>({});
  const [failed, setFailed] = useState<Record<string, boolean>>({});

  // Read once on mount. Never read localStorage during render — that would
  // desync SSR/client and throw a hydration error.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          const seen = new Set<string>();
          const clean = parsed
            .filter((t): t is string => typeof t === "string")
            .map((t) => t.trim())
            .filter((t) => t && !seen.has(t.toLowerCase()) && seen.add(t.toLowerCase()));
          setTopics(clean);
        }
      }
    } catch {
      // Corrupt value — ignore and start empty.
    }
    setHydrated(true);
  }, []);

  // Persist. Gated on `hydrated` so the initial empty state never clobbers
  // stored topics before the read effect runs; try/catch swallows Safari
  // private-mode quota errors.
  useEffect(() => {
    if (!hydrated || typeof window === "undefined") return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(topics));
    } catch {
      // Quota / private mode — nothing to do.
    }
  }, [topics, hydrated]);

  function add(topic: string) {
    const clean = topic.trim().slice(0, 100);
    if (!clean) return;
    setTopics((prev) =>
      prev.some((t) => t.toLowerCase() === clean.toLowerCase()) ? prev : [...prev, clean]
    );
  }

  function remove(topic: string) {
    setTopics((prev) => prev.filter((t) => t !== topic));
  }

  // Fetch the newest few bills per tracked topic. allSettled so one dead topic
  // (or a down backend) degrades that topic's rows only, never the whole panel.
  useEffect(() => {
    let live = true;
    if (!topics.length) {
      setByTopic({});
      setFailed({});
      return;
    }
    const jz = jurisdiction ? `&jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
    const getJson = async (path: string) => {
      const res = await fetch(`${API_URL}${path}`);
      if (!res.ok) throw new Error(`${path} -> ${res.status}`);
      return res.json();
    };
    // Primary: /civic/bills?topic= (topic-hub filter). Fallback: the advisory
    // brief's citations, which are always topic-scoped, if bills is unavailable.
    const load = async (topic: string): Promise<WatchItem[]> => {
      const t = encodeURIComponent(topic);
      try {
        const r = await getJson(`/civic/bills?topic=${t}&limit=3${jz}`);
        return (r.bills as WatchItem[]) ?? [];
      } catch {
        const r = await getJson(`/civic/insights/brief?topic=${t}${jz}`);
        return ((r.citations as { file_no: string; title: string }[]) ?? [])
          .slice(0, 3)
          .map((c) => ({ file_no: c.file_no, title: c.title, status: null, intro_date: null }));
      }
    };
    Promise.allSettled(topics.map(load)).then((results) => {
      if (!live) return;
      const next: Record<string, WatchItem[]> = {};
      const nextFailed: Record<string, boolean> = {};
      results.forEach((res, i) => {
        const topic = topics[i];
        if (res.status === "fulfilled") next[topic] = res.value;
        else nextFailed[topic] = true;
      });
      setByTopic(next);
      setFailed(nextFailed);
    });
    return () => {
      live = false;
    };
  }, [topics, jurisdiction]);

  const jz = jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : "";

  return (
    <section className="watchlist" style={{ marginTop: 24 }}>
      <p className="eyebrow">civicscope · Tracked topics</p>
      <div className="panel">
        <form
          className="wl-input-row"
          onSubmit={(e) => {
            e.preventDefault();
            add(input);
            setInput("");
          }}
        >
          <input
            type="text"
            placeholder="Track a topic (e.g. lead paint)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            aria-label="Track a topic"
          />
          <button type="submit" disabled={!input.trim()}>
            Add
          </button>
        </form>

        <div className="examples">
          {QUICK_TOPICS.filter(
            (q) => !topics.some((t) => t.toLowerCase() === q.toLowerCase())
          ).map((q) => (
            <button
              key={q}
              type="button"
              className="example-chip"
              onClick={() => add(q)}
            >
              + {q}
            </button>
          ))}
        </div>

        {hydrated && topics.length === 0 && (
          <p className="note">
            Track a topic to get a daily digest of new legislation on it.
          </p>
        )}

        {topics.map((topic) => {
          const items = (byTopic[topic] ?? []).filter((it) => it.file_no);
          return (
            <div key={topic} className="wl-topic">
              <p className="section-title">
                <Link href={`/topic/${encodeURIComponent(topic)}${jz}`}>{topic}</Link>
                <button
                  type="button"
                  className="wl-remove"
                  onClick={() => remove(topic)}
                  aria-label={`Stop tracking ${topic}`}
                >
                  ×
                </button>
              </p>
              {failed[topic] ? (
                <p className="note">Couldn&apos;t load recent bills.</p>
              ) : items.length === 0 ? (
                <p className="note">No recent bills.</p>
              ) : (
                <ul className="citations">
                  {items.map((it) => (
                    <li key={it.file_no}>
                      <div className="cite-button">
                        <Link
                          className="cite-id"
                          href={`/bill/${encodeURIComponent(it.file_no as string)}${jz}`}
                        >
                          #{it.file_no}
                        </Link>
                        <span className="cite-title">
                          {it.title}
                          {it.intro_date ? ` · ${it.intro_date}` : ""}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
