"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Mirrors app/civic/schemas.py: TrendsResponse.
type Trend = { topic: string; series: number[] };
type TrendsData = { years: number[]; topics: Trend[] };

// A tiny inline-SVG sparkline of one topic's per-year counts.
export function Sparkline({ series }: { series: number[] }) {
  if (series.length < 2) return null;
  const w = 150;
  const h = 26;
  const max = Math.max(...series, 1);
  const pts = series
    .map((v, i) => `${(i / (series.length - 1)) * w},${h - (v / max) * (h - 2) - 1}`)
    .join(" ");
  return (
    <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth="1.5" />
    </svg>
  );
}

// Multi-year topic activity trends. Hides itself if the backend is down or the
// corpus spans fewer than two years (nothing meaningful to trend).
export default function Trends({
  jurisdiction = "",
  panel = false,
}: {
  jurisdiction?: string;
  panel?: boolean;
}) {
  const [data, setData] = useState<TrendsData | null>(null);

  useEffect(() => {
    let live = true;
    const qs = jurisdiction ? `?jurisdiction=${encodeURIComponent(jurisdiction)}` : "";
    fetch(`${API_URL}/civic/insights/trends${qs}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d: TrendsData) => live && setData(d))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [jurisdiction]);

  if (!data || data.years.length < 2) return null;
  const first = data.years[0];
  const last = data.years[data.years.length - 1];

  return (
    <div className={panel ? "panel trends" : "trends"}>
      <p className="section-title">
        Topic activity over time <span className="hint">— {first}–{last} (bills/year)</span>
      </p>
      <ul className="trend-list">
        {data.topics.map((t) => (
          <li key={t.topic} className="trend-row">
            <span className="trend-label">{t.topic}</span>
            <Sparkline series={t.series} />
            <span className="trend-total">{t.series.reduce((a, b) => a + b, 0)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
