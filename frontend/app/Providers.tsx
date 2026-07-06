"use client";

import { AuthProvider } from "./AuthContext";

// Thin client boundary so layout.tsx can stay a server component while still
// mounting the auth context around Nav and the page tree.
export default function Providers({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}
