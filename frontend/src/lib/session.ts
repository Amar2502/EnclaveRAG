import type { AuthResponse, AuthUser } from "./types";

const STORAGE_KEY = "enclave_rag_session";

export interface StoredSession {
  access_token: string;
  user: AuthUser;
}

export const DEMO_MODE_ENABLED: boolean =
  process.env.NEXT_PUBLIC_ENABLE_DEMO_MODE === "true" ||
  (process.env.NEXT_PUBLIC_ENABLE_DEMO_MODE !== "false" &&
    process.env.NODE_ENV !== "production");

export function getSession(): StoredSession | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as StoredSession;
    if (!parsed.access_token || !parsed.user?.user_id) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function saveSession(auth: AuthResponse): StoredSession {
  const session: StoredSession = {
    access_token: auth.access_token,
    user: auth.user,
  };
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  }
  return session;
}

export function clearSession(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(STORAGE_KEY);
  }
}
