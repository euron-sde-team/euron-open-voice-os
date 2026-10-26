"use client";

import { BookOpenIcon, ExternalLinkIcon, GlobeIcon, KeyRoundIcon, PlugIcon, RouteIcon, ServerIcon, ShieldIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { CodeBlock } from "@/components/code-block";
import { PageHeader } from "@/components/page-header";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { useAgents } from "@/features/agents/api";
import { browserSnippet, openaiProviderSnippet, pythonSnippet, startSessionSnippet, websocketSnippet } from "@/lib/snippets";

function Step({ n, icon: Icon, title, body, children }: { n: number; icon: typeof ServerIcon; title: string; body: React.ReactNode; children: React.ReactNode }) {
  return (
    <Surface className="flex flex-col">
      <div className="flex items-start gap-3 px-5 pt-5 pb-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary">
          <Icon className="size-4" />
        </span>
        <div>
          <h2 className="text-[14px] font-semibold">
            <span className="mr-1.5 text-faint tabular">{n}.</span>
            {title}
          </h2>
          <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">{body}</p>
        </div>
      </div>
      <div className="mt-auto px-5 pb-5">{children}</div>
    </Surface>
  );
}

export function IntegrationsScreen() {
  const [origin, setOrigin] = React.useState("");
  React.useEffect(() => setOrigin(window.location.origin), []);
  const agents = useAgents();
  const agentId = agents.data?.[0]?.id ?? "AGENT_ID";

  return (
    <>
      <PageHeader
        title="Integrations"
        description="Put a VoiceOS agent in your own app: your backend asks for a one-minute session ticket, the browser connects to the runtime with it."
      />
      <div className="space-y-4">
        <Surface className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <div className="flex items-start gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary">
              <KeyRoundIcon className="size-4" />
            </span>
            <div>
              <h2 className="text-[14px] font-semibold">
                <span className="mr-1.5 text-faint tabular">1.</span>
                Create an SDK key
              </h2>
              <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">
                Keys live on your server, never in the browser. Scope one to the agents and website origins that may use it.
              </p>
            </div>
          </div>
          <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/keys" />}>
            <KeyRoundIcon />
            Manage SDK keys
          </Button>
        </Surface>
        <div className="grid gap-4 xl:grid-cols-2">
          <Step
            n={2}
            icon={ServerIcon}
            title="Ask for a session ticket"
            body="Your backend trades the key for a ticket: the runtime URLs, a single-use token valid for one minute, and the disclosure to show the caller."
          >
            <CodeBlock
              samples={[
                { id: "curl", label: "curl", code: startSessionSnippet(origin, "vos_...", agentId) },
                { id: "py", label: "Python", code: pythonSnippet(origin, "vos_...", agentId) },
              ]}
            />
          </Step>
          <Step
            n={3}
            icon={GlobeIcon}
            title="Connect from the browser"
            body="Any Pipecat client works. WebRTC gives the lowest latency and the browser's echo cancellation; the WebSocket transport is the fallback."
          >
            <CodeBlock
              samples={[
                { id: "webrtc", label: "WebRTC", code: browserSnippet() },
                { id: "ws", label: "WebSocket", code: websocketSnippet() },
              ]}
            />
          </Step>
        </div>
        <Surface>
          <SurfaceHeader
            title="Bring any provider"
            description="Every stage speaks the OpenAI API shape, so self-hosted servers and the rest of the Euron AI stack plug in as providers"
          />
          <div className="grid gap-4 px-5 pb-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <CodeBlock samples={[{ id: "providers", label: "Provider base URLs", code: openaiProviderSnippet() }]} />
            <div className="space-y-3">
              {[
                {
                  icon: ShieldIcon,
                  name: "TokenShield",
                  body: "Point an LLM provider at TokenShield to put every conversation's language model spend under a hard budget.",
                  href: "https://github.com/euron-sde-team/euron-open-tokenshield",
                },
                {
                  icon: RouteIcon,
                  name: "SmartRouter",
                  body: 'Use model "auto" through SmartRouter to answer each turn with the cheapest model that fits.',
                  href: "https://github.com/euron-sde-team/euron-open-smart-router",
                },
              ].map((p) => (
                <div key={p.name} className="rounded-xl bg-muted/60 p-4">
                  <div className="flex items-center gap-2">
                    <p.icon className="size-4 text-primary" />
                    <h3 className="text-[14px] font-semibold">{p.name}</h3>
                  </div>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted-foreground">{p.body}</p>
                  <Button className="mt-2.5" size="xs" variant="subtle" nativeButton={false} render={<a href={p.href} target="_blank" rel="noreferrer" />}>
                    Project
                    <ExternalLinkIcon />
                  </Button>
                </div>
              ))}
              <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/providers" />}>
                <PlugIcon />
                Add a provider
              </Button>
            </div>
          </div>
        </Surface>
        <Surface className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <BookOpenIcon className="size-4 text-primary" />
            The full contract, with every field and error code, is in the interactive API reference.
          </div>
          <Button size="sm" variant="outline" nativeButton={false} render={<a href={`${origin}/docs`} target="_blank" rel="noreferrer" />}>
            Open /docs
            <ExternalLinkIcon />
          </Button>
        </Surface>
      </div>
    </>
  );
}
