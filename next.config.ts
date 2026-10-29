import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  distDir: process.env.NEXT_DIST_DIR || '.next',
  async redirects() {
    return ['v2', 'v3', 'v4', 'v5'].map((version) => ({
      source: `/${version}/:path*`,
      destination: '/v1',
      permanent: false,
    }));
  },
};

export default nextConfig;
