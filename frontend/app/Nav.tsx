"use client";

import Link from "next/link";
import { useAuth } from "./AuthContext";

// Slim sticky top bar shared across every route (rendered once in the root
// layout). The static route links are pure next/link markup; the auth-dependent
// slot is gated on `ready` so SSR/first paint stays stable (no hydration
// mismatch) — the provider owns the /me call, Nav never fetches.
export default function Nav() {
  const { user, ready, logout } = useAuth();
  return (
    <nav className="nav">
      <div className="nav-inner">
        <Link href="/" className="nav-brand">
          civicscope
        </Link>
        <div className="nav-links">
          <Link href="/browse">Browse</Link>
          <Link href="/analytics">Analytics</Link>
          <Link href="/compare">Compare</Link>
          <Link href="/about">About</Link>
          {ready &&
            (user ? (
              <>
                <span className="nav-user">{user.email}</span>
                <button type="button" className="nav-logout" onClick={logout}>
                  Log out
                </button>
              </>
            ) : (
              <Link href="/account">Sign in</Link>
            ))}
        </div>
      </div>
    </nav>
  );
}
