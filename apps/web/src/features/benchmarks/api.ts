"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { qk, STALE } from "@/lib/query-keys";

export function useBenchmarkRuns() {
  return useQuery({
    queryKey: qk.benchmarks,
    queryFn: () => unwrap(api.GET("/api/v1/benchmarks", { params: { query: { limit: 20 } } })),
    staleTime: STALE.live,
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 2_000 : false),
  });
}

export function useQueueBenchmark() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { agent_ids: string[]; sessions: number }) =>
      unwrap(api.POST("/api/v1/benchmarks", { body: { kind: "latency", ...body } })),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.benchmarks }),
  });
}
