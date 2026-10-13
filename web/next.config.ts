import type { NextConfig } from "next";

const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Windows local builds may not have symlink privileges; Docker builds on
  // Linux always produce standalone. Local Windows can still use next start.
  output: process.platform === "win32" ? undefined : "standalone",
  typedRoutes: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiBase}/:path*`,
      },
    ];
  },
};

export default nextConfig;
