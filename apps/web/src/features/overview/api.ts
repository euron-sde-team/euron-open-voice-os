"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { qk, STALE } from "@/lib/query-keys";

export function useOverview(days: number) {
  return useQuery({
    queryKey: qk.overview(days),
    queryFn: () => unwrap(api.GET("/api/v1/analytics/overview", { params: { query: { days } } })),
    staleTime: STALE.analytics,
    refetchInterval: 30_000,
  });
}
