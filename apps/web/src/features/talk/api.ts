"use client";

import { useMutation } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

/** A one-minute ticket for exactly one session with this agent. */
export function useStartSession() {
  return useMutation({
    mutationFn: (agentId: string) => unwrap(api.POST("/api/v1/sessions", { body: { agent_id: agentId } })),
  });
}
