import type { Metadata } from "next";
import { Suspense } from "react";

import { SessionsScreen } from "@/features/sessions/components/sessions-screen";

export const metadata: Metadata = { title: "Sessions" };

export default function Page() {
  return (
    <Suspense>
      <SessionsScreen />
    </Suspense>
  );
}
