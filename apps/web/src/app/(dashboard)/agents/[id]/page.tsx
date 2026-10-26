import type { Metadata } from "next";

import { AgentEditor } from "@/features/agents/components/agent-editor";

export const metadata: Metadata = { title: "Agent" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AgentEditor id={id} />;
}
