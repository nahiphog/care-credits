import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  distDir: process.env.NEXT_DIST_DIR || '.next',
  async redirects() {
    return ['v1', 'v2', 'v3', 'v4', 'v5', 'live'].map((legacyPath) => ({
      source: `/${legacyPath}/:path*`,
      destination: '/',
      permanent: false,
    }));
  },
};

export default nextConfig;
