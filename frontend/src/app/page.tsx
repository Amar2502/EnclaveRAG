"use client";

import { ArrowRight, Building2, Lock, Moon, ShieldCheck, Sparkles, Sun } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { DEMO_MODE_ENABLED, getSession } from "@/lib/session";
import { useAppStore } from "@/store/useAppStore";

export default function LandingPage() {
  const [loggedInOrg, setLoggedInOrg] = useState<string | null>(null);
  const theme = useAppStore((s) => s.theme);
  const toggleTheme = useAppStore((s) => s.toggleTheme);

  useEffect(() => {
    const session = getSession();
    if (session) {
      setLoggedInOrg(session.user.org_name);
    }
  }, []);

  return (
    <div className="min-h-screen bg-[#060a12] text-slate-100">
      <header className="border-b border-slate-800/80 bg-[#0b111e]/90">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <span className="text-base font-bold text-white">EnclaveRAG</span>
          </div>

          <div className="flex items-center gap-2.5 text-xs font-semibold">
            <button
              type="button"
              onClick={toggleTheme}
              className="rounded-lg border border-slate-700 bg-slate-900 p-2 text-slate-300 hover:text-white"
              title={theme === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode"}
            >
              {theme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            </button>
            {DEMO_MODE_ENABLED && (
              <Link
                href="/demo"
                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-amber-300 hover:bg-amber-500/20"
              >
                <Sparkles className="h-3.5 w-3.5" />
                Dev Demo
              </Link>
            )}
            <Link
              href="/login"
              className="rounded-lg border border-slate-700 px-3.5 py-2 text-slate-200 hover:border-slate-500"
            >
              Sign in
            </Link>
            <Link
              href="/signup"
              className="rounded-lg bg-sky-600 px-3.5 py-2 text-white hover:bg-sky-500"
            >
              Create Organization
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-20 text-center">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-300">
          <Lock className="h-3.5 w-3.5" />
          Private Company Knowledge · Role & Department Access Control
        </div>
        <h1 className="mx-auto max-w-3xl text-4xl font-bold tracking-tight text-white sm:text-5xl">
          Instant Answers From Your Company Docs — Strictly Within Your Permissions
        </h1>
        <p className="mx-auto mt-5 max-w-2xl text-base text-slate-400">
          EnclaveRAG keeps every department&apos;s policies, handbooks, and confidential files
          isolated by organization, role, and access level so employees only see what they are
          authorized to read.
        </p>

        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          {loggedInOrg ? (
            <Link
              href="/workspace"
              className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-3 text-sm font-semibold text-white hover:bg-emerald-500"
            >
              Continue to {loggedInOrg}
              <ArrowRight className="h-4 w-4" />
            </Link>
          ) : (
            <>
              <Link
                href="/signup"
                className="inline-flex items-center gap-2 rounded-xl bg-sky-600 px-5 py-3 text-sm font-semibold text-white hover:bg-sky-500"
              >
                <Building2 className="h-4 w-4" />
                Onboard Your Organization
              </Link>
              <Link
                href="/login"
                className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-5 py-3 text-sm font-semibold text-slate-200 hover:border-slate-500"
              >
                Employee Sign In
              </Link>
            </>
          )}
        </div>

        <div className="mt-16 grid grid-cols-1 gap-4 text-left md:grid-cols-3">
          <FeatureCard
            title="Zero Cross-Team Leaks"
            body="Every search is scoped to your organization, department, and clearance tier before answers are generated."
          />
          <FeatureCard
            title="Instant Access Controls"
            body="Admins can update document visibility, change team permissions, or sign out sessions in one click."
          />
          <FeatureCard
            title="Verified Source Citations"
            body="Every answer links directly to the underlying company documents so employees can read or download the original file."
          />
        </div>
      </main>
    </div>
  );
}

function FeatureCard({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-[#0b111e] p-5">
      <h2 className="text-sm font-semibold text-white">{title}</h2>
      <p className="mt-2 text-xs leading-relaxed text-slate-400">{body}</p>
    </div>
  );
}
