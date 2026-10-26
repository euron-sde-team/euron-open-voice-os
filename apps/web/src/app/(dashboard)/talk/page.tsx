import { Suspense } from "react";

import { TalkScreen } from "@/features/talk/components/talk-screen";

export const metadata = { title: "Talk" };

export default function TalkPage() {
  return (
    <Suspense>
      <TalkScreen />
    </Suspense>
  );
}
