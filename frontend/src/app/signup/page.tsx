"use client";

import { Building2, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { registerOrg } from "@/lib/api";
import { saveSession } from "@/lib/session";

export default function SignupPage() {
  const router = useRouter();
  const [orgName, setOrgName] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [department, setDepartment] = useState("Executive");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const auth = await registerOrg({
        org_name: orgName,
        full_name: fullName,
        email,
        password,
        department,
      });
      saveSession(auth);
      router.push("/admin");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#060a12] px-4 py-10">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-[#0b111e] p-7 shadow-xl">
        <div className="mb-6 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white">Create Your Organization</h1>
            <p className="text-xs text-slate-400">
              Provisions an isolated tenant with L4 Org Admin access
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3.5 text-sm">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-300">
              Organization Name
            </label>
            <input
              required
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              placeholder="Acme Robotics"
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2 text-white outline-none focus:border-sky-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-300">Your Full Name</label>
            <input
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Jordan Taylor"
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2 text-white outline-none focus:border-sky-500"
            />
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-300">Work Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@acme.com"
                className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2 text-white outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-300">Department</label>
              <input
                required
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2 text-white outline-none focus:border-sky-500"
              />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-300">
              Password (min 8 characters)
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
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-sky-600 px-4 py-2.5 font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
          >
            <Building2 className="h-4 w-4" />
            {loading ? "Provisioning..." : "Create Organization"}
          </button>
        </form>

        <p className="mt-5 text-center text-xs text-slate-400">
          Already have an account?{" "}
          <Link href="/login" className="font-semibold text-sky-400 hover:text-sky-300">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
