"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { ProviderIn, ProviderUpdate } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

export function useProviders() {
  return useQuery({
    queryKey: qk.providers,
    queryFn: () => unwrap(api.GET("/api/v1/providers", { params: { query: { stage: null } } })),
    staleTime: STALE.config,
  });
}

function useInvalidate() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: qk.providers });
    void client.invalidateQueries({ queryKey: qk.agents });
  };
}

export function useCreateProvider() {
  const done = useInvalidate();
  return useMutation({ mutationFn: (body: ProviderIn) => unwrap(api.POST("/api/v1/providers", { body })), onSuccess: done });
}

export function useUpdateProvider() {
  const done = useInvalidate();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ProviderUpdate }) =>
      unwrap(api.PATCH("/api/v1/providers/{provider_id}", { params: { path: { provider_id: id } }, body })),
    onSuccess: done,
  });
}

export function useDeleteProvider() {
  const done = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/providers/{provider_id}", { params: { path: { provider_id: id } } })),
    onSuccess: done,
  });
}

export function useTestProvider() {
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/providers/{provider_id}/test", { params: { path: { provider_id: id } } })),
  });
}
