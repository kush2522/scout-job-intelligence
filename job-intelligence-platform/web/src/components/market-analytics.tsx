"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type SearchTerm = { query: string; searches: number };
type Trend = { date: string; new_jobs: number; hiring_companies: number };

function Meter({ value, max, color = "bg-cyan-300" }: { value: number; max: number; color?: string }) {
  return <div className="h-2 overflow-hidden rounded-full bg-white/10"><div className={`h-full ${color}`} style={{ width: `${Math.max(3, (value / Math.max(1, max)) * 100)}%` }}/></div>;
}

export function MarketAnalytics() {
  const [terms, setTerms] = useState<SearchTerm[]>([]);
  const [trends, setTrends] = useState<Trend[]>([]);
  useEffect(() => {
    let disposed = false;
    Promise.all([fetch(`${API}/api/analytics/search-terms?days=30&limit=10`), fetch(`${API}/api/analytics/trends?days=30`)]).then(async responses => {
      if (responses.some(response => !response.ok)) throw new Error("Analytics unavailable");
      const [searchData, trendData] = await Promise.all(responses.map(response => response.json()));
      if (!disposed) { setTerms(searchData); setTrends(trendData); }
    }).catch(() => { if (!disposed) { setTerms([]); setTrends([]); } });
    return () => { disposed = true; };
  }, []);

  const jobMax = Math.max(1, ...trends.map(day => day.new_jobs));
  const companyMax = Math.max(1, ...trends.map(day => day.hiring_companies));
  const termMax = Math.max(1, ...terms.map(term => term.searches));
  return <div className="mt-6 grid gap-5 lg:grid-cols-2">
    <section className="rounded-2xl border border-white/10 p-5" aria-labelledby="popular-searches">
      <div className="flex items-end justify-between gap-3"><div><h2 id="popular-searches" className="text-lg font-semibold">Candidate search demand</h2><p className="mt-1 text-xs text-slate-500">Top submitted keyword searches · last 30 days</p></div><span className="text-xs text-slate-500">Aggregate only</span></div>
      {terms.length ? <div className="mt-5 space-y-4">{terms.map(term => <div key={term.query}><div className="mb-2 flex justify-between gap-3 text-sm"><span className="truncate text-slate-300">{term.query}</span><span className="text-slate-400">{term.searches}</span></div><Meter value={term.searches} max={termMax}/></div>)}</div> : <p className="mt-5 text-sm text-slate-500">Search demand will appear as candidates submit searches.</p>}
    </section>
    <section className="rounded-2xl border border-white/10 p-5" aria-labelledby="hiring-trend">
      <div><h2 id="hiring-trend" className="text-lg font-semibold">Hiring activity</h2><p className="mt-1 text-xs text-slate-500">New active roles and employers detected each day · last 30 days</p></div>
      {trends.length ? <div className="mt-5 max-h-64 space-y-2 overflow-y-auto pr-2">{trends.map(day => <div key={day.date} className="grid grid-cols-[5.5rem_1fr_5rem] items-center gap-3 text-xs"><span className="text-slate-500">{new Date(`${day.date}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span><div className="space-y-1"><Meter value={day.new_jobs} max={jobMax}/><Meter value={day.hiring_companies} max={companyMax} color="bg-violet-300"/></div><span className="text-right text-slate-400">{day.new_jobs} roles<br/>{day.hiring_companies} employers</span></div>)}</div> : <p className="mt-5 text-sm text-slate-500">Daily hiring trends will appear after job sources are collected.</p>}
      <p className="mt-4 text-[11px] text-slate-600">Counts reflect Scout’s connected sources and collection coverage.</p>
    </section>
  </div>;
}
