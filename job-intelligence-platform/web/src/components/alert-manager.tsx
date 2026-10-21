"use client";

import { useEffect, useState } from "react";
import { signIn, useSession } from "next-auth/react";

type SavedSearch = {
  id: number; name: string; query: string | null; location: string | null;
  company: string | null; remote: boolean | null; employment_type: string | null;
  posted_within_days: number | null; frequency: string; active: boolean;
  last_sent_at: string | null;
};

export function AlertManager({ query, location, company, remote, employmentType, postedWithinDays }: {
  query: string; location: string; company: string; remote: boolean;
  employmentType: string; postedWithinDays: string;
}) {
  const { status } = useSession();
  const [frequency, setFrequency] = useState("daily");
  const [items, setItems] = useState<SavedSearch[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const hasFilters = Boolean(query.trim() || location.trim() || company.trim() || remote || employmentType || postedWithinDays);

  async function refresh() {
    const response = await fetch("/api/portal/saved-searches", { cache: "no-store" });
    if (!response.ok) throw new Error("Saved searches are unavailable. Check the portal configuration.");
    setItems(await response.json());
  }

  useEffect(() => {
    if (status !== "authenticated") return;
    let disposed = false;
    fetch("/api/portal/saved-searches", { cache: "no-store" })
      .then(async response => {
        if (!response.ok) throw new Error("Saved searches are unavailable. Check the portal configuration.");
        return response.json();
      })
      .then((result: SavedSearch[]) => { if (!disposed) setItems(result); })
      .catch(error => { if (!disposed) setMessage(error.message); });
    return () => { disposed = true; };
  }, [status]);

  async function create() {
    setLoading(true); setMessage("");
    const name = query.trim() || company.trim() || location.trim() || (remote ? "Remote jobs" : "My job search");
    try {
      const response = await fetch("/api/portal/saved-searches", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: `${name} jobs`, query: query.trim() || null,
          location: location.trim() || null, company: company.trim() || null,
          remote: remote || null, employment_type: employmentType || null,
          posted_within_days: postedWithinDays ? Number(postedWithinDays) : null, frequency }),
      });
      if (!response.ok) throw new Error((await response.json()).detail || "Could not save this alert.");
      const result = await response.json();
      await refresh();
      setMessage(result.email_delivery_configured
        ? "Saved. New matching roles will be emailed on your selected schedule."
        : "Saved. Email delivery will start after the operator configures the mail provider.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save this alert.");
    } finally { setLoading(false); }
  }

  async function update(item: SavedSearch, changes: { active?: boolean }) {
    const response = await fetch(`/api/portal/saved-searches/${item.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes),
    });
    if (response.ok) await refresh();
    else setMessage("Could not update this alert. Please try again.");
  }

  async function remove(item: SavedSearch) {
    const response = await fetch(`/api/portal/saved-searches/${item.id}`, { method: "DELETE" });
    if (response.ok) await refresh();
    else setMessage("Could not delete this alert. Please try again.");
  }

  return <section className="mt-7 rounded-2xl border border-cyan-300/20 bg-cyan-300/[.04] p-5" aria-labelledby="alert-title">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><p className="text-xs font-bold tracking-[.18em] text-cyan-200">JOB ALERTS</p>
        <h3 id="alert-title" className="mt-2 text-xl font-semibold">Get matching roles by email</h3>
        <p className="mt-1 text-sm text-slate-400">Save this search and choose how often you want a digest.</p></div>
      {status === "authenticated" ? <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="alert-frequency">Email frequency</label>
        <select id="alert-frequency" value={frequency} onChange={event => setFrequency(event.target.value)} className="rounded-xl border border-white/10 bg-slate-950 px-3 py-3 text-sm">
          <option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option>
        </select>
        <button disabled={!hasFilters || loading} onClick={() => void create()} className="rounded-xl bg-cyan-300 px-4 py-3 text-sm font-bold text-slate-950 disabled:opacity-50">
          {loading ? "Saving…" : "Create email alert"}
        </button>
      </div> : <button onClick={() => void signIn("google", { redirectTo: "/" })} className="rounded-xl border border-white/10 px-4 py-3 text-sm font-semibold hover:border-cyan-300/50">
        Sign in to create an alert
      </button>}
    </div>
    {status === "authenticated" && items.length > 0 && <div className="mt-5 space-y-2">
      {items.map(item => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-slate-950/60 px-4 py-3">
        <div><p className="text-sm font-medium">{item.name}</p><p className="mt-1 text-xs text-slate-500">{[item.query, item.location, item.company, item.remote ? "Remote" : null, item.employment_type, item.posted_within_days ? `Past ${item.posted_within_days} days` : null].filter(Boolean).join(" · ")} · {item.frequency}</p></div>
        <div className="flex items-center gap-3 text-xs">
          <button onClick={() => void update(item, { active: !item.active })} className="text-cyan-200">{item.active ? "Pause" : "Resume"}</button>
          <button onClick={() => void remove(item)} className="text-slate-400 hover:text-rose-200">Delete</button>
        </div>
      </div>)}
    </div>}
    {message && <p role="status" className="mt-3 text-sm text-slate-300">{message}</p>}
  </section>;
}
