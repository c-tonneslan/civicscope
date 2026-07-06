"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Namespaced key, matching the Watchlist convention.
const STORAGE_KEY = "Docket.auth.token";

type User = { id: number; email: string };

type AuthState = {
  user: User | null;
  token: string | null;
  // False until the mount effect has read localStorage and (if present)
  // validated the stored token. Consumers gate auth-dependent UI on this to
  // keep SSR and first paint stable.
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

// Error carrying the HTTP status so the form can map it to a message.
class AuthError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function postCredentials(path: string, email: string, password: string): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    // Backend unreachable — status 0 signals a network failure to the caller.
    throw new AuthError(0, "network");
  }
  if (!res.ok) {
    throw new AuthError(res.status, `${path} -> ${res.status}`);
  }
  const data = await res.json();
  return data.token as string;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  // Fetch the account for a token. Returns "ok" | "unauthorized" | "unreachable"
  // so callers can decide whether to clear a stored token or keep it.
  const loadMe = useCallback(async (t: string): Promise<"ok" | "unauthorized" | "unreachable"> => {
    let res: Response;
    try {
      res = await fetch(`${API_URL}/civic/auth/me`, {
        headers: { Authorization: `Bearer ${t}` },
      });
    } catch {
      return "unreachable";
    }
    if (res.status === 401) return "unauthorized";
    if (!res.ok) return "unreachable";
    try {
      const data = await res.json();
      setUser({ id: data.id, email: data.email });
      setToken(t);
      return "ok";
    } catch {
      return "unreachable";
    }
  }, []);

  // On mount: read the stored token and validate it. Never read localStorage
  // during render — that would desync SSR/client and throw.
  useEffect(() => {
    if (typeof window === "undefined") return;
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(STORAGE_KEY);
    } catch {
      stored = null;
    }
    if (!stored) {
      setReady(true);
      return;
    }
    let live = true;
    loadMe(stored).then((result) => {
      if (!live) return;
      if (result === "unauthorized") {
        try {
          window.localStorage.removeItem(STORAGE_KEY);
        } catch {
          // ignore
        }
      } else if (result === "unreachable") {
        // Backend down — keep the token, leave user null, still render.
        setToken(stored);
      }
      setReady(true);
    });
    return () => {
      live = false;
    };
  }, [loadMe]);

  const persist = useCallback((t: string) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, t);
    } catch {
      // Quota / private mode — nothing to do.
    }
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const t = await postCredentials("/civic/auth/login", email, password);
      persist(t);
      setToken(t);
      const result = await loadMe(t);
      if (result === "unauthorized") throw new AuthError(401, "invalid token");
    },
    [loadMe, persist]
  );

  const signup = useCallback(
    async (email: string, password: string) => {
      const t = await postCredentials("/civic/auth/signup", email, password);
      persist(t);
      setToken(t);
      const result = await loadMe(t);
      if (result === "unauthorized") throw new AuthError(401, "invalid token");
    },
    [loadMe, persist]
  );

  const logout = useCallback(() => {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, ready, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
