import type { Metadata } from "next";
import { Suspense } from "react";

import { AgentsScreen } from "@/features/agents/components/agents-screen";

export const metadata: Metadata = { title: "Agents" };

export default function Page() {
  return (
    <Suspense>
      <AgentsScreen />
    </Suspense>
  );
}
