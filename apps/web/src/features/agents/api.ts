"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { AgentIn, AgentUpdate } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

export function useAgents() {
  return useQuery({
    queryKey: qk.agents,
    queryFn: () => unwrap(api.GET("/api/v1/agents")),
    staleTime: STALE.config,
  });
}

export function useAgent(id: string | null) {
  return useQuery({
    queryKey: qk.agent(id ?? ""),
    queryFn: () => unwrap(api.GET("/api/v1/agents/{agent_id}", { params: { path: { agent_id: id ?? "" } } })),
    enabled: !!id,
    staleTime: STALE.config,
  });
}

export function useTemplates() {
  return useQuery({
    queryKey: qk.templates,
    queryFn: () => unwrap(api.GET("/api/v1/agents/templates")),
    staleTime: STALE.static,
  });
}

function useInvalidate() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: qk.agents });
    void client.invalidateQueries({ queryKey: qk.providers });
  };
}

export function useCreateAgent() {
  const done = useInvalidate();
  return useMutation({
    mutationFn: (body: AgentIn) => unwrap(api.POST("/api/v1/agents", { body })),
    onSuccess: done,
  });
}

export function useCreateFromTemplate() {
  const done = useInvalidate();
  return useMutation({
    mutationFn: (body: { template: string; name?: string | null }) =>
      unwrap(api.POST("/api/v1/agents/from-template", { body })),
    onSuccess: done,
  });
}

export function useUpdateAgent() {
  const done = useInvalidate();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AgentUpdate }) =>
      unwrap(api.PATCH("/api/v1/agents/{agent_id}", { params: { path: { agent_id: id } }, body })),
    onSuccess: done,
  });
}

export function useDeleteAgent() {
  const done = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/agents/{agent_id}", { params: { path: { agent_id: id } } })),
    onSuccess: done,
  });
}
