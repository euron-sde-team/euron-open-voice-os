"use client";

import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { qk, STALE } from "@/lib/query-keys";

export interface SessionFilters {
  agent_id?: string;
  errors_only?: boolean;
}

export function useSessions(filters: SessionFilters, limit = 50) {
  return useInfiniteQuery({
    queryKey: qk.sessions({ ...filters, limit }),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/sessions", {
          params: {
            query: {
              cursor: pageParam,
              limit,
              agent_id: filters.agent_id || null,
              errors_only: filters.errors_only ?? false,
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
    placeholderData: keepPreviousData,
    staleTime: STALE.live,
    refetchInterval: 10_000,
  });
}

export function useSession(id: string | null) {
  return useQuery({
    queryKey: qk.session(id ?? ""),
    queryFn: () => unwrap(api.GET("/api/v1/sessions/{session_id}", { params: { path: { session_id: id ?? "" } } })),
    enabled: !!id,
    staleTime: STALE.static,
    retry: (count, err) => count < 4 && (err as { status?: number })?.status === 404, // just ended: the report may still be on its way
    retryDelay: 1500,
  });
}

export function useEraseTranscript() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/v1/sessions/{session_id}/transcript", { params: { path: { session_id: id } } })),
    onSuccess: (_d, id) => {
      void client.invalidateQueries({ queryKey: qk.session(id) });
      void client.invalidateQueries({ queryKey: qk.sessionsAll });
    },
  });
}
