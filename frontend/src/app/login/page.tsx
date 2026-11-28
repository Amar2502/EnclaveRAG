"use client";

import { Lock, Moon, ShieldCheck, Sun } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { loginUser, requestPasswordReset } from "@/lib/api";
import { saveSession } from "@/lib/session";
import { useAppStore } from "@/store/useAppStore";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const revoked = searchParams.get("revoked") === "1";
  const theme = useAppStore((s) => s.theme);
  const toggleTheme = useAppStore((s) => s.toggleTheme);
  const setClearanceLabels = useAppStore((s) => s.setClearanceLabels);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [forgotMode, setForgotMode] = useState(false);
  const [resetMessage, setResetMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setResetMessage(null);
    try {
      if (forgotMode) {
        await requestPasswordReset(email);
        setResetMessage(
          "If an active account matches that email, a password reset link has been sent.",
        );
        return;
      }
      const auth = await loginUser({ email, password });
      saveSession(auth);
      setClearanceLabels(auth.user.clearance_labels);
      router.push(auth.user.is_org_admin ? "/admin" : "/workspace");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-[#060a12] px-4">
      <button
        type="button"
        onClick={toggleTheme}
        className="absolute right-4 top-4 rounded-lg border border-slate-700 bg-slate-900 p-2 text-slate-300 hover:text-white"
        title={theme === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode"}
      >
        {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </button>
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-[#0b111e] p-7 shadow-xl">
        <div className="mb-6 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white">Sign in to EnclaveRAG</h1>
            <p className="text-xs text-slate-400">Access your organization knowledge base</p>
          </div>
        </div>

        {revoked && (
          <div className="mb-4 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-200">
            Your session was revoked or updated by an organization admin. Please sign in again.
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4 text-sm">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-300">Work Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2.5 text-white outline-none focus:border-sky-500"
            />
          </div>
          {!forgotMode && (
            <div>
              <div className="mb-1 flex items-center justify-between">
                <label className="block text-xs font-medium text-slate-300">Password</label>
                <button
                  type="button"
                  onClick={() => {
                    setForgotMode(true);
                    setError(null);
                  }}
                  className="text-[11px] font-medium text-sky-400 hover:text-sky-300"
                >
                  Forgot password?
                </button>
              </div>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2.5 text-white outline-none focus:border-sky-500"
              />
            </div>
          )}

          {error && <p className="text-xs text-rose-400">{error}</p>}
          {resetMessage && <p className="text-xs text-emerald-400">{resetMessage}</p>}

          <button
            type="submit"
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-sky-600 px-4 py-2.5 font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
          >
            <Lock className="h-4 w-4" />
            {loading
              ? forgotMode
                ? "Sending..."
                : "Signing in..."
              : forgotMode
                ? "Send Reset Link"
                : "Sign in"}
          </button>

          {forgotMode && (
            <button
              type="button"
              onClick={() => {
                setForgotMode(false);
                setResetMessage(null);
                setError(null);
              }}
              className="w-full text-center text-xs text-slate-400 hover:text-white"
            >
              Back to Sign in
            </button>
          )}
        </form>

        <p className="mt-5 text-center text-xs text-slate-400">
          Setting up a new company?{" "}
          <Link href="/signup" className="font-semibold text-sky-400 hover:text-sky-300">
            Create Organization
          </Link>
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#060a12]" />}>
      <LoginForm />
    </Suspense>
  );
}
