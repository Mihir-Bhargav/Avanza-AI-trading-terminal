import path from "node:path";
import type { NextConfig } from "next";

// The browser always calls same-origin /api/*; Next forwards it to the Python
// backend. No CORS needed, and on Vercel API_PROXY_TARGET points at the hosted
// backend instead of localhost.
const API_PROXY_TARGET = (process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8777").replace(/\/$/, "");

const nextConfig: NextConfig = {
  // Pin the workspace root: a stray lockfile higher up the tree otherwise confuses Turbopack.
  turbopack: { root: path.join(__dirname) },
  // Lets two dev servers run side by side (NEXT_DIST_DIR=.next-a / .next-b) without sharing a build dir.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  devIndicators: false,
  // The proxy's default 30 s limit cut off Ask Kes answers (claude -p can take a minute or more).
  experimental: { proxyTimeout: 240_000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_PROXY_TARGET}/api/:path*` }];
  },
};

export default nextConfig;
