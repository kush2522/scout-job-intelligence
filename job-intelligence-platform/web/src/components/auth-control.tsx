"use client";

import { signIn, signOut, useSession } from "next-auth/react";
import { useState } from "react";

export function AuthControl() {
  const { data, status } = useSession();
  const [error, setError] = useState("");

  async function login() {
    setError("");
    try {
      await signIn("google", { redirectTo: "/" });
    } catch {
      setError("Google sign-in could not start. Check the OAuth setup and try again.");
    }
  }

  if (status === "loading") {
    return <span className="text-xs text-slate-500">Loading account…</span>;
  }

  if (data?.user) {
    return <div className="flex items-center gap-3">
      <span className="hidden max-w-48 truncate text-sm text-slate-300 sm:inline">{data.user.name || data.user.email}</span>
      <button onClick={() => void signOut({ redirectTo: "/" })} className="rounded-xl border border-white/10 px-4 py-2 text-sm text-slate-200 hover:border-cyan-300/50">Sign out</button>
    </div>;
  }

  return <div className="flex flex-col items-end">
    <button onClick={() => void login()} className="rounded-xl border border-white/10 px-4 py-2 text-sm font-semibold text-slate-200 hover:border-cyan-300/50">Continue with Google</button>
    {error && <span role="status" className="mt-1 text-[11px] text-amber-200">{error}</span>}
  </div>;
}
