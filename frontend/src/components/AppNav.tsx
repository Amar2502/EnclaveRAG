"use client";

import { LogOut, Moon, ShieldCheck, Sun, UserCog } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { logoutUser } from "@/lib/api";
import { clearSession, DEMO_MODE_ENABLED } from "@/lib/session";
import type { AuthUser } from "@/lib/types";
import { useAppStore } from "@/store/useAppStore";
import { ClearanceBadge } from "./ClearanceBadge";
import { ProfileModal } from "./ProfileModal";

export function AppNav({ user, token }: { user: AuthUser; token: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const theme = useAppStore((s) => s.theme);
  const toggleTheme = useAppStore((s) => s.toggleTheme);

  const [currentUser, setCurrentUser] = useState<AuthUser>(user);
  const [showProfile, setShowProfile] = useState(false);

  async function handleLogout() {
    try {
      await logoutUser(token);
    } catch {
      // Clear local session even if token was already revoked
    }
    clearSession();
    router.push("/login");
  }

  return (
    <>
      <header className="border-b border-slate-800/80 bg-[#0b111e]/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3.5">
          <div className="flex items-center gap-4">
            <Link href="/workspace" className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                <div className="text-sm font-bold text-white">EnclaveRAG</div>
                <div className="text-[11px] text-slate-400">{currentUser.org_name}</div>
              </div>
            </Link>

            <nav className="flex items-center gap-1 text-xs">
              <Link
                href="/workspace"
                className={`rounded-lg px-3 py-1.5 font-medium transition ${
                  pathname === "/workspace"
                    ? "bg-slate-800 text-white"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                Workspace
              </Link>
              {currentUser.is_org_admin && (
                <Link
                  href="/admin"
                  className={`rounded-lg px-3 py-1.5 font-medium transition ${
                    pathname === "/admin"
                      ? "bg-slate-800 text-white"
                      : "text-slate-400 hover:text-white"
                  }`}
                >
                  Admin Console
                </Link>
              )}
              {DEMO_MODE_ENABLED && (
                <Link
                  href="/demo"
                  className="rounded-lg px-3 py-1.5 font-medium text-amber-300/80 hover:text-amber-200"
                >
                  Dev Demo
                </Link>
              )}
            </nav>
          </div>

          <div className="flex items-center gap-2.5 text-xs">
            <button
              type="button"
              onClick={toggleTheme}
              className="rounded-lg border border-slate-700 bg-slate-900 p-1.5 text-slate-300 hover:border-slate-600 hover:text-white"
              title={theme === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode"}
            >
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>

            <button
              type="button"
              onClick={() => setShowProfile(true)}
              className="hidden items-center gap-2 rounded-lg border border-transparent px-2 py-1 text-right hover:border-slate-700 hover:bg-slate-900 sm:flex"
              title="Account settings & password"
            >
              <div>
                <div className="font-semibold text-slate-100">{currentUser.full_name}</div>
                <div className="text-[11px] text-slate-400">
                  {currentUser.department} · {currentUser.role_title}
                </div>
              </div>
              <UserCog className="h-3.5 w-3.5 text-slate-400" />
            </button>

            <ClearanceBadge level={currentUser.clearance_level} />
            <button
              type="button"
              onClick={() => void handleLogout()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-medium text-slate-300 hover:border-slate-600 hover:text-white"
            >
              <LogOut className="h-3.5 w-3.5" />
              Sign out
            </button>
          </div>
        </div>
      </header>

      <ProfileModal
        open={showProfile}
        user={currentUser}
        token={token}
        onClose={() => setShowProfile(false)}
        onUpdated={setCurrentUser}
      />
    </>
  );
}
