/**
 * Query keys in one place, so invalidation after a mutation names exactly what it
 * touched.
 */
export const qk = {
  me: ["auth", "me"] as const,
  system: ["system"] as const,
  users: ["users"] as const,
  keys: (includeRevoked = false) => ["keys", { includeRevoked }] as const,
  keysAll: ["keys"] as const,
  providers: ["providers"] as const,
  agents: ["agents"] as const,
  agent: (id: string) => ["agents", "detail", id] as const,
  templates: ["agents", "templates"] as const,
  sessions: (filters: object) => ["sessions", "list", filters] as const,
  session: (id: string) => ["sessions", "detail", id] as const,
  sessionsAll: ["sessions"] as const,
  overview: (days: number) => ["analytics", "overview", days] as const,
  analyticsAll: ["analytics"] as const,
  benchmarks: ["benchmarks"] as const,
  audit: (action?: string) => ["audit", { action }] as const,
};

/** staleTime per kind of data, chosen deliberately (see docs/architecture/HLD.md). */
export const STALE = {
  analytics: 15_000,
  config: 30_000,
  live: 5_000,
  static: 5 * 60_000,
} as const;
