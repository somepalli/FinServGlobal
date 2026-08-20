import type { NextConfig } from "next";

// The API is reached server-side only. Nothing regulated should ever be
// fetched from the browser, so there is no NEXT_PUBLIC_ API base URL here.
const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          {
            key: "Content-Security-Policy",
            value: "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'",
          },
        ],
      },
    ];
  },
};

export default config;
