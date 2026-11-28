"use client";

import { KeyRound, User, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { updateMyProfile } from "@/lib/api";
import { getSession, saveSession } from "@/lib/session";
import type { AuthUser } from "@/lib/types";

export function ProfileModal({
  open,
  user,
  token,
  onClose,
  onUpdated,
}: {
  open: boolean;
  user: AuthUser;
  token: string;
  onClose: () => void;
  onUpdated: (updated: AuthUser) => void;
}) {
  const [fullName, setFullName] = useState(user.full_name);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const updated = await updateMyProfile(token, {
        full_name: fullName.trim() || undefined,
        ...(newPassword
          ? { current_password: currentPassword, new_password: newPassword }
          : {}),
      });
      const mergedUser: AuthUser = { ...user, full_name: updated.full_name };
      const existing = getSession();
      if (existing) {
        saveSession({ ...existing, user: mergedUser });
      }
      onUpdated(mergedUser);
      setCurrentPassword("");
      setNewPassword("");
      setMessage("Account settings updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update profile.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-[#0d1424] p-5 shadow-2xl">
        <div className="mb-4 flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <User className="h-4 w-4 text-sky-400" />
            <h3 className="text-sm font-bold text-white">Account Settings</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-700 p-1 text-slate-400 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3 text-xs">
          <div>
            <label className="mb-1 block text-slate-300">Display Name</label>
            <input
              type="text"
              required
              minLength={2}
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
            />
          </div>

          <div className="border-t border-slate-800 pt-3">
            <div className="mb-2 flex items-center gap-1.5 font-semibold text-slate-300">
              <KeyRound className="h-3.5 w-3.5 text-amber-400" />
              Change Password (optional)
            </div>
            <div className="space-y-2">
              <input
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="Current password"
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
              />
              <input
                type="password"
                minLength={8}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="New password (min 8 characters)"
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
              />
            </div>
          </div>

          {error && <p className="text-rose-400">{error}</p>}
          {message && <p className="text-emerald-400">{message}</p>}

          <button
            type="submit"
            disabled={saving}
            className="w-full rounded-xl bg-sky-600 py-2 font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save Changes"}
          </button>
        </form>
      </div>
    </div>
  );
}
