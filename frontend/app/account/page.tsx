"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../AuthContext";

type Mode = "login" | "signup";

// Map an error thrown by login/signup to a human message. AuthError carries the
// HTTP status; status 0 means the backend was unreachable.
function messageFor(err: unknown): string {
  const status = (err as { status?: number })?.status;
  if (status === 409) return "That email is already registered.";
  if (status === 401) return "Wrong email or password.";
  if (status === 400 || status === 422)
    return "Enter a valid email and an 8+ character password.";
  return "Couldn't reach the server. Try again.";
}

export default function AccountPage() {
  const { user, ready, login, signup } = useAuth();
  const router = useRouter();

  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Already signed in — send them home.
  useEffect(() => {
    if (ready && user) router.replace("/");
  }, [ready, user, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const trimmed = email.trim();
    if (!trimmed || password.length < 8) {
      setError("Enter a valid email and an 8+ character password.");
      return;
    }
    setSubmitting(true);
    try {
      if (mode === "signup") await signup(trimmed, password);
      else await login(trimmed, password);
      router.push("/");
    } catch (err) {
      setError(messageFor(err));
      setSubmitting(false);
    }
  }

  function toggle() {
    setMode((m) => (m === "login" ? "signup" : "login"));
    setError(null);
  }

  return (
    <main className="container">
      <header className="page-header">
        <nav className="breadcrumb" aria-label="Breadcrumb">
          <span>Docket</span>
          <span className="sep">›</span>
          <span className="current">
            {mode === "login" ? "Sign in" : "Create account"}
          </span>
        </nav>
        <h1>{mode === "login" ? "Sign in" : "Create account"}</h1>
        <div className="page-header-meta">
          <span>Sync your watchlist across devices.</span>
        </div>
      </header>
      <section>
        <div className="panel">
          <form className="auth-form" onSubmit={onSubmit}>
            <div>
              <label htmlFor="auth-email">Email</label>
              <input
                id="auth-email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <label htmlFor="auth-password">Password</label>
              <input
                id="auth-password"
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error && <p className="status-err">{error}</p>}
            <button type="submit" disabled={submitting}>
              {submitting
                ? "Working…"
                : mode === "login"
                  ? "Sign in"
                  : "Create account"}
            </button>
          </form>
          <p className="note">
            {mode === "login" ? "Need an account? " : "Already have an account? "}
            <button type="button" className="auth-toggle" onClick={toggle}>
              {mode === "login" ? "Create one" : "Sign in"}
            </button>
          </p>
        </div>
      </section>
    </main>
  );
}
