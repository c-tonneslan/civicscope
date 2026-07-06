import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Nothing exotic for the demo slice. The browser talks to the backend
  // directly via NEXT_PUBLIC_API_URL, so no rewrites/proxy are needed.

  // Pin the file-tracing root to this frontend dir. A stray lockfile in a parent
  // dir makes Next infer the wrong workspace root (warning at build time and
  // incorrect file tracing); pinning it here keeps tracing scoped to the app.
  outputFileTracingRoot: path.join(__dirname),
};

export default nextConfig;
