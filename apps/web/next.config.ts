import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Emit a minimal, self-contained server for container images.
  output: "standalone",
  // In a pnpm monorepo, trace workspace files from the repo root so the
  // standalone bundle includes everything the server needs.
  outputFileTracingRoot: path.join(__dirname, "../../"),
};

export default nextConfig;
