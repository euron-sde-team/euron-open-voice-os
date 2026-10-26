"use client";

import { BotIcon, MicIcon, PhoneOffIcon, ShieldCheckIcon, TriangleAlertIcon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { Segmented } from "@/components/segmented";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Field } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useAgents } from "@/features/agents/api";
import type { Agent } from "@/lib/api/types";
import { languageLabel } from "@/lib/chips";
import { cn } from "@/lib/cn";
import { formatLatency } from "@/lib/format";

import { useStartSession } from "../api";
import { type Line, type Phase, type TransportChoice, useVoiceSession } from "../use-voice-session";

const PHASE_LABEL: Record<Phase, string> = {
  idle: "Ready when you are",
  connecting: "Connecting...",
  listening: "Listening",
  user: "You are speaking",
  thinking: "Thinking",
  agent: "Speaking",
  ended: "Conversation ended",
  error: "Something went wrong",
};

function Orb({ phase, level }: { phase: Phase; level: number }) {
  const live = phase === "listening" || phase === "user" || phase === "thinking" || phase === "agent";
  const scale = 1 + Math.min(level, 1) * 0.35;
  return (
    <div className="relative mx-auto flex size-44 items-center justify-center sm:size-52" aria-hidden>
      <div
        className={cn(
          "absolute inset-0 rounded-full bg-gradient-to-br from-[var(--stage-stt)] to-[var(--primary)] opacity-20 blur-2xl transition-transform duration-150",
          phase === "thinking" && "animate-pulse",
        )}
        style={{ transform: `scale(${live ? scale : 0.9})` }}
      />
      <div
        className={cn(
          "relative flex size-32 items-center justify-center rounded-full bg-gradient-to-br from-[var(--stage-stt)] to-[var(--primary)] shadow-[var(--elev-3)] transition-transform duration-100 sm:size-36",
          !live && "opacity-80 grayscale-[30%]",
        )}
        style={{ transform: `scale(${live ? 0.94 + Math.min(level, 1) * 0.12 : 1})` }}
      >
        <svg viewBox="0 0 64 32" className="w-16 text-white">
          {[6, 14, 22, 30, 38, 46, 54].map((x, i) => {
            const base = [6, 12, 20, 26, 20, 12, 6][i] ?? 8;
            const h = live ? Math.max(4, base * (0.35 + Math.min(level, 1) * 1.6)) : base * 0.5;
            return <rect key={x} x={x - 2} y={16 - h / 2} width="4" height={h} rx="2" fill="currentColor" opacity={0.95} />;
          })}
        </svg>
      </div>
    </div>
  );
}

function Transcript({ lines, phase }: { lines: Line[]; phase: Phase }) {
  const end = React.useRef<HTMLDivElement | null>(null);
  React.useEffect(() => end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }), [lines]);
  if (!lines.length) {
    return (
      <p className="px-1 py-6 text-center text-[13px] text-muted-foreground">
        {phase === "idle"
          ? "Press Start, allow the microphone, and say hello. Your words and the agent's answers appear here."
          : phase === "connecting"
            ? "Connecting to the voice runtime..."
            : "Say something: the agent is listening."}
      </p>
    );
  }
  return (
    <ol className="space-y-2.5" aria-live="polite" data-testid="transcript">
      {lines.map((l) => (
        <li key={l.id} className={cn("flex", l.who === "user" ? "justify-end" : "justify-start")}>
          <div
            className={cn(
              "max-w-[85%] rounded-2xl px-3.5 py-2 text-[13.5px] leading-relaxed",
              l.who === "user" ? "rounded-br-md bg-primary text-primary-foreground" : "rounded-bl-md bg-muted text-foreground",
              !l.final && "opacity-80",
            )}
            data-who={l.who}
          >
            <span>{l.text || (l.who === "agent" ? "..." : "")}</span>
            {l.who === "agent" && (l.responseMs != null || l.interrupted) && (
              <span className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                {l.responseMs != null && <span title="From when you stopped talking to the first audio, measured in this browser">answered in {formatLatency(l.responseMs)}</span>}
                {l.interrupted && <span className="font-medium text-warning">interrupted</span>}
              </span>
            )}
          </div>
        </li>
      ))}
      <div ref={end} />
    </ol>
  );
}

function Disclosure({ agent }: { agent: Agent }) {
  const external = agent.external_providers;
  return external.length ? (
    <div className="flex gap-2.5 rounded-xl bg-warning-soft px-3.5 py-3 text-[12.5px]" role="note" data-testid="disclosure">
      <TriangleAlertIcon className="mt-0.5 size-4 shrink-0 text-warning" />
      <p>
        This agent sends your audio or its transcript to <strong>{external.join(", ")}</strong> to understand and answer you.
      </p>
    </div>
  ) : (
    <div className="flex gap-2.5 rounded-xl bg-savings-soft px-3.5 py-3 text-[12.5px]" role="note" data-testid="disclosure">
      <ShieldCheckIcon className="mt-0.5 size-4 shrink-0 text-savings" />
      <p>Audio and transcripts stay on this deployment&apos;s own servers.</p>
    </div>
  );
}

export function TalkScreen() {
  const agents = useAgents();
  const params = useSearchParams();
  const startSession = useStartSession();
  const [agentId, setAgentId] = React.useState<string>("");
  const [choice, setChoice] = React.useState<TransportChoice>("auto");
  const enabled = (agents.data ?? []).filter((a) => a.enabled);
  const agent = enabled.find((a) => a.id === agentId) ?? enabled[0];

  React.useEffect(() => {
    const wanted = params.get("agent");
    if (wanted && enabled.some((a) => a.id === wanted)) setAgentId(wanted);
  }, [params, enabled]);

  const getTicket = React.useCallback(() => startSession.mutateAsync(agent?.id ?? ""), [startSession, agent?.id]);
  const { state, start, stop, audioRef } = useVoiceSession(getTicket);
  const busy = state.phase !== "idle" && state.phase !== "ended" && state.phase !== "error";
  const level = state.phase === "agent" ? state.agentLevel : state.micLevel;

  if (agents.isPending) {
    return (
      <>
        <PageHeader title="Talk" description="Have a real conversation with one of your agents, right here in the browser." />
        <Skeleton className="h-[28rem] w-full rounded-2xl" />
      </>
    );
  }
  if (agents.isError && !agents.data) {
    return (
      <>
        <PageHeader title="Talk" />
        <Surface>
          <ErrorState error={agents.error} onRetry={() => void agents.refetch()} />
        </Surface>
      </>
    );
  }
  if (!agent) {
    return (
      <>
        <PageHeader title="Talk" description="Have a real conversation with one of your agents, right here in the browser." />
        <Surface>
          <EmptyState
            icon={BotIcon}
            title="No agent to talk to yet"
            description="Create an agent from a template: it picks the self-hosted speech providers by default, so it works without any API key."
            action={
              <Button nativeButton={false} render={<Link href="/agents?new=1" />}>
                Create an agent
              </Button>
            }
          />
        </Surface>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Talk"
        description="Have a real conversation with one of your agents, right here in the browser. Interrupt it any time."
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,4fr)]">
        <Surface className="flex flex-col">
          <div className="flex flex-col items-center gap-4 px-5 pt-8 pb-5">
            <Orb phase={state.phase} level={level} />
            <div className="text-center">
              <div className="text-[15px] font-semibold" data-testid="phase">
                {PHASE_LABEL[state.phase]}
              </div>
              <div className="mt-0.5 text-[12.5px] text-muted-foreground">
                {agent.name}
                {state.transport && <> &middot; {state.transport === "webrtc" ? "WebRTC" : "WebSocket"}</>}
              </div>
            </div>
            {busy ? (
              <Button variant="destructive-soft" size="lg" onClick={() => void stop()}>
                <PhoneOffIcon />
                End conversation
              </Button>
            ) : (
              <Button size="lg" onClick={() => void start(choice)} disabled={startSession.isPending}>
                <MicIcon />
                {state.phase === "ended" || state.phase === "error" ? "Talk again" : "Start talking"}
              </Button>
            )}
            {state.phase === "error" && state.error && (
              <p role="alert" className="max-w-md text-center text-[13px] text-danger">
                {state.error}
              </p>
            )}
            {state.phase === "ended" && state.sessionId && (
              <p className="text-[12.5px] text-muted-foreground">
                Timings, cost and transcript:{" "}
                <Link className="font-medium text-primary hover:underline" href={`/sessions?session=${state.sessionId}`}>
                  open this session
                </Link>{" "}
                (it appears a few seconds after the call ends).
              </p>
            )}
          </div>
          <div className="mx-5 mb-5 max-h-[26rem] min-h-40 overflow-y-auto rounded-xl bg-muted/50 p-3.5">
            <Transcript lines={state.lines} phase={state.phase} />
          </div>
          {/* The agent's voice (WebRTC). The WebSocket transport plays audio itself. */}
          <audio ref={audioRef} autoPlay className="hidden" />
        </Surface>

        <div className="space-y-4">
          <Surface>
            <SurfaceHeader title="Agent" description="Who you are talking to" />
            <div className="space-y-4 px-5 pb-5">
              <Field label="Agent" htmlFor="talk-agent">
                <SimpleSelect
                  id="talk-agent"
                  value={agent.id}
                  disabled={busy}
                  onValueChange={(v) => setAgentId(v)}
                  options={enabled.map((a) => ({ value: a.id, label: `${a.name} (${languageLabel(a.language)})` }))}
                />
              </Field>
              <Field label={<span className="inline-flex items-center gap-1">Connection <Hint term="transport" /></span>}>
                <Segmented<TransportChoice>
                  ariaLabel="Connection"
                  value={choice}
                  onChange={setChoice}
                  options={[
                    { value: "auto", label: "Auto" },
                    { value: "webrtc", label: "WebRTC" },
                    { value: "websocket", label: "WebSocket" },
                  ]}
                />
              </Field>
              <Disclosure agent={agent} />
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[12.5px]">
                <dt className="text-muted-foreground">Listens with</dt>
                <dd className="truncate">{agent.stt.name}</dd>
                <dt className="text-muted-foreground">Thinks with</dt>
                <dd className="truncate">{agent.llm.name}{agent.llm.model ? ` (${agent.llm.model})` : ""}</dd>
                <dt className="text-muted-foreground">Speaks with</dt>
                <dd className="truncate">{agent.tts.name}{agent.voice ? ` (${agent.voice})` : ""}</dd>
              </dl>
              <div className="flex flex-wrap gap-1.5">
                {agent.turn.allow_interruptions && <Chip tone="primary">Interruptible</Chip>}
                <Chip tone="neutral">{agent.turn.mode === "smart" ? "Smart turn detection" : "Silence detection"}</Chip>
                {agent.privacy.transcript_retention_days === 0 ? <Chip tone="savings">No transcript kept</Chip> : <Chip tone="neutral">Transcript kept {agent.privacy.transcript_retention_days} d</Chip>}
              </div>
            </div>
          </Surface>
          <Surface>
            <SurfaceHeader title="Tips" />
            <ul className="space-y-1.5 px-5 pb-5 text-[12.5px] text-muted-foreground">
              <li>Use headphones, or the agent may hear itself on speakers.</li>
              <li>Talk over the agent to interrupt: it stops and listens.</li>
              <li>Pause mid-sentence if you like: the turn detector waits for you to finish.</li>
            </ul>
          </Surface>
        </div>
      </div>
    </>
  );
}
