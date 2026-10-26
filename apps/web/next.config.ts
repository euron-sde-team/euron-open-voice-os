import type { NextConfig } from "next";

/**
 * Same-origin deployment: the browser only ever talks to this origin. Next proxies the
 * admin API, the OpenAI-compatible gateway and the health probes to the API service, so
 * the httpOnly session cookie stays first-party and no CORS is needed. In production a
 * load balancer may route these paths straight to the API before they reach Next.
 */
const apiInternal = (process.env.API_INTERNAL_URL || "http://localhost:4530").replace(/\/+$/, "");

const prod = process.env.NODE_ENV === "production";

const nextConfig: NextConfig = {
  // One self-contained server bundle (`node server.js`), the unit a container image ships.
  output: "standalone",
  outputFileTracingRoot: __dirname,
  poweredByHeader: false,
  devIndicators: false,
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiInternal}/api/:path*` },
      { source: "/v1/:path*", destination: `${apiInternal}/v1/:path*` },
      { source: "/healthz", destination: `${apiInternal}/healthz` },
      { source: "/readyz", destination: `${apiInternal}/readyz` },
      { source: "/docs", destination: `${apiInternal}/docs` },
      { source: "/openapi.json", destination: `${apiInternal}/openapi.json` },
      { source: "/health", destination: `${apiInternal}/health` },
    ];
  },
  async headers() {
    const common = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "X-Frame-Options", value: "DENY" },
      // The Talk page needs the microphone of this origin; nothing else does.
      { key: "Permissions-Policy", value: "camera=(), microphone=(self), geolocation=(), payment=()" },
      // Browsers honour HSTS only over HTTPS, so this is inert on http://localhost.
      ...(prod ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }] : []),
    ];
    // The Content-Security-Policy is set per request in middleware.ts: it names the voice
    // runtime's origin, which is deployment config read at run time, not build time.
    return [{ source: "/:path*", headers: common }];
  },
};

export default nextConfig;
