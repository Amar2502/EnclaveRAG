"use client";

import { ShieldCheck, UserCheck } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { acceptInvite } from "@/lib/api";
import { saveSession } from "@/lib/session";

function AcceptInviteForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [token, setToken] = useState(searchParams.get("token") ?? "");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const auth = await acceptInvite({ token, full_name: fullName, password });
      saveSession(auth);
      router.push("/workspace");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not accept invitation.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#060a12] px-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-[#0b111e] p-7 shadow-xl">
        <div className="mb-6 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white">Accept Invitation</h1>
            <p className="text-xs text-slate-400">Activate your organization account</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3.5 text-sm">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-300">Invite Token</label>
            <input
              required
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Paste invite token"
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2 font-mono text-xs text-white outline-none focus:border-sky-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-300">Full Name</label>
            <input
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Alex Rivera"
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2 text-white outline-none focus:border-sky-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-300">
              Choose Password (min 8 chars)
            </label>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2 text-white outline-none focus:border-sky-500"
            />
          </div>

          {error && <p className="text-xs text-rose-400">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            <UserCheck className="h-4 w-4" />
            {loading ? "Activating..." : "Join Workspace"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#060a12]" />}>
      <AcceptInviteForm />
    </Suspense>
  );
}
