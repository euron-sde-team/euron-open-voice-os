import type { Metadata } from "next";

import { KeysScreen } from "@/features/keys/components/keys-screen";

export const metadata: Metadata = { title: "SDK keys" };

export default function Page() {
  return <KeysScreen />;
}
