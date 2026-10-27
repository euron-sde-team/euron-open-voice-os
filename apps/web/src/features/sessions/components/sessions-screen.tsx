"use client";

import { AudioLinesIcon, MessagesSquareIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { Surface } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { SimpleSelect } from "@/components/ui/select";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAgents } from "@/features/agents/api";
import { usePermissions } from "@/features/auth/api";
import { ApiError, errorMessage } from "@/lib/api/errors";
import type { VoiceSession, VoiceSessionDetail } from "@/lib/api/types";
import { costStatus, endReason } from "@/lib/chips";
import { formatDateTime, formatLatency, formatNumber, formatRelative, formatUsd } from "@/lib/format";

import { type SessionFilters, useEraseTranscript, useSession, useSessions } from "../api";
import { TurnWaterfall, WaterfallLegend } from "./turn-waterfall";

function duration(s: number): string {
  if (s < 60) return `${Math.round(s)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

function Cost({ s }: { s: Pick<VoiceSession, "cost_total_usd" | "cost_status"> }) {
  const spec = costStatus(s.cost_status);
  if (s.cost_status === "self_hosted") return <Chip tone={spec.tone} title={spec.hint}>{spec.label}</Chip>;
  if (s.cost_total_usd == null) return <span className="text-[12px] text-faint" title={spec.hint}>Not reported</span>;
  return (
    <span className="tabular" title={spec.hint}>
      {formatUsd(s.cost_total_usd)}
      {s.cost_status === "partial" && <span className="ml-1 text-[11px] text-warning">partial</span>}
    </span>
  );
}

function Stat({ label, children, hint }: { label: string; children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-muted/70 px-3 py-2.5">
      <div className="flex items-center gap-1 text-[11.5px] text-muted-foreground">
        {label}
        {hint}
      </div>
      <div className="mt-0.5 text-[15px] font-semibold tabular">{children}</div>
    </div>
  );
}

function Detail({ d }: { d: VoiceSessionDetail }) {
  const { canWrite } = usePermissions();
  const erase = useEraseTranscript();
  const [confirm, setConfirm] = React.useState(false);
  const scale = Math.max(1000, ...d.turns.map((t) => Math.max(t.response_ms ?? 0, t.stt_ms ?? 0)));
  const u = d.usage as Record<string, number | boolean>;
  return (
    <>
      <div className="flex flex-wrap gap-1.5">
        <Chip tone={endReason(d.end_reason).tone} title={endReason(d.end_reason).hint}>{endReason(d.end_reason).label}</Chip>
        <Chip tone="neutral">{d.transport === "webrtc" ? "WebRTC" : "WebSocket"}</Chip>
        {d.external_providers.length ? (
          <Chip tone="warning" title="Providers outside your infrastructure that received audio or text">Sent to {d.external_providers.join(", ")}</Chip>
        ) : (
          <Chip tone="savings">Stayed on your servers</Chip>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Stat label="Duration">{duration(d.duration_s)}</Stat>
        <Stat label="Response, median" hint={<Hint term="responseTime" />}>{d.response_ms_p50 != null ? formatLatency(d.response_ms_p50) : "n/a"}</Stat>
        <Stat label="Interruptions" hint={<Hint term="interruption" />}>{d.interruptions}</Stat>
        <Stat label="Cost (est.)" hint={<Hint term="cost" />}><Cost s={d} /></Stat>
        <Stat label="Saved by caches" hint={<Hint term="savings" />}>{formatUsd(d.savings_usd)}</Stat>
        <Stat label="LLM tokens">{formatNumber(Number(u.llm_input_tokens ?? 0) + Number(u.llm_output_tokens ?? 0))}</Stat>
      </div>
      <section>
        <h3 className="mb-2 text-[13px] font-semibold">Cost by stage</h3>
        <dl className="grid grid-cols-3 gap-2 text-[12.5px]">
          {(["stt", "llm", "tts"] as const).map((k) => {
            const v = d[`cost_${k}_usd` as const];
            const hosted = d.self_hosted_stages.includes(k);
            return (
              <div key={k} className="rounded-lg bg-muted/60 px-3 py-2">
                <dt className="text-muted-foreground">{k.toUpperCase()}</dt>
                <dd className={hosted ? "font-medium text-savings" : "font-medium tabular"}>
                  {hosted ? "Self-hosted" : v == null ? "not reported" : formatUsd(v)}
                </dd>
              </div>
            );
          })}
        </dl>
        <p className="mt-1.5 text-[11.5px] text-muted-foreground">
          {formatNumber(Number(u.stt_audio_seconds ?? 0))} s of audio recognized, {formatNumber(Number(u.tts_characters ?? 0))} characters spoken
          {Number(u.tts_characters_cached ?? 0) > 0 && <> ({formatNumber(Number(u.tts_characters_cached))} from the phrase cache)</>}.
        </p>
      </section>
      <section>
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="text-[13px] font-semibold">Turns</h3>
          {canWrite && d.transcript_stored && (
            <Button variant="subtle" size="xs" onClick={() => setConfirm(true)}>
              <Trash2Icon />
              Erase transcript
            </Button>
          )}
        </div>
        <WaterfallLegend />
        <ol className="mt-3 space-y-3">
          {d.turns.map((t) => (
            <li key={t.index} className="rounded-xl bg-muted/50 p-3">
              {t.user_text && <p className="text-[13px]"><span className="font-medium text-primary">Caller: </span>{t.user_text}</p>}
              {t.agent_text && (
                <p className="mt-1 text-[13px]">
                  <span className="font-medium">Agent: </span>
                  {t.agent_text}
                  {t.interrupted && <span className="ml-1.5 text-[11.5px] font-medium text-warning">interrupted</span>}
                  {t.response_cache_hit && <span className="ml-1.5 text-[11.5px] font-medium text-savings">from cache</span>}
                </p>
              )}
              {!t.user_text && !t.agent_text && (
                <p className="text-[12.5px] text-muted-foreground">{d.transcript_stored ? "No words in this turn." : "Words not kept (retention), timings below."}</p>
              )}
              {t.response_ms != null && (
                <div className="mt-2 space-y-1">
                  <TurnWaterfall turn={t} scaleMs={scale} />
                  <div className="text-[11.5px] text-muted-foreground tabular">
                    Answered in {formatLatency(t.response_ms)}
                    {t.llm_model && <> &middot; {t.llm_model}{t.llm_routed_small && " (small model)"}</>}
                  </div>
                </div>
              )}
              {t.error && <p className="mt-1.5 text-[12px] text-danger">{t.error}</p>}
            </li>
          ))}
        </ol>
        {!d.turns.length && <p className="text-[13px] text-muted-foreground">Nobody spoke in this session.</p>}
      </section>
      {d.errors.length > 0 && (
        <section>
          <h3 className="mb-2 text-[13px] font-semibold">Errors</h3>
          <ul className="space-y-1 text-[12.5px] text-danger">{d.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
        </section>
      )}
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Erase this transcript?"
        description="The words are removed now. Timings, usage and cost stay for analytics."
        confirmLabel="Erase transcript"
        pending={erase.isPending}
        onConfirm={() => erase.mutate(d.id, { onSuccess: () => { toast.success("Transcript erased."); setConfirm(false); }, onError: (e) => toast.error(errorMessage(e)) })}
      />
    </>
  );
}

function SessionDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const q = useSession(id);
  const pending = q.isError && q.error instanceof ApiError && q.error.status === 404;
  return (
    <Sheet open={id != null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{q.data?.agent_name ?? "Session"}</SheetTitle>
          <SheetDescription>{q.data ? `${formatDateTime(q.data.started_at)}, ${q.data.subject.startsWith("key:") ? "SDK key" : "dashboard"}` : "Loading"}</SheetDescription>
        </SheetHeader>
        <SheetBody className="space-y-6">
          {q.isError && !pending && <ErrorState compact error={q.error} onRetry={() => void q.refetch()} />}
          {pending && <p className="text-[13px] text-muted-foreground">This session is not stored yet: the runtime reports it a few seconds after the call ends.</p>}
          {!q.data && !q.isError && <Skeleton className="h-64 w-full" />}
          {q.data && <Detail d={q.data} />}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}

export function SessionsScreen() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const agents = useAgents();
  const [filters, setFilters] = React.useState<SessionFilters>({});
  const q = useSessions(filters);
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  const openId = params.get("session");
  const open = (id: string | null) => router.replace(id == null ? pathname : `${pathname}?session=${id}`, { scroll: false });

  return (
    <>
      <PageHeader
        title="Sessions"
        description="Every finished conversation: what was said (when retention allows), how fast each answer came, and what it cost."
      />
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <SimpleSelect
          aria-label="Agent"
          className="w-56"
          value={filters.agent_id ?? "all"}
          onValueChange={(v) => setFilters((f) => ({ ...f, agent_id: v === "all" ? undefined : v }))}
          options={[{ value: "all", label: "All agents" }, ...(agents.data ?? []).map((a) => ({ value: a.id, label: a.name }))]}
        />
        <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Switch checked={!!filters.errors_only} onCheckedChange={(v) => setFilters((f) => ({ ...f, errors_only: v }))} aria-label="Only sessions with errors" />
          Only sessions with errors
        </label>
      </div>
      <Surface className="overflow-hidden">
        {q.isPending ? (
          <div className="pt-3"><TableSkeleton rows={8} cols={6} /></div>
        ) : q.isError && !q.data ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : !items.length ? (
          <EmptyState
            icon={MessagesSquareIcon}
            title={filters.agent_id || filters.errors_only ? "No sessions match" : "No sessions yet"}
            description="Each conversation appears here a few seconds after it ends, with its turns, response times and cost."
            action={
              <Button size="sm" nativeButton={false} render={<Link href="/talk" />}>
                <AudioLinesIcon />
                Talk to an agent
              </Button>
            }
          />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead className="hidden md:table-cell">Length</TableHead>
                  <TableHead className="hidden sm:table-cell">Turns</TableHead>
                  <TableHead>Response</TableHead>
                  <TableHead className="hidden lg:table-cell">Ended</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((s) => (
                  <TableRow
                    key={s.id}
                    tabIndex={0}
                    role="button"
                    aria-label={`Open session with ${s.agent_name}, ${formatRelative(s.started_at)}`}
                    className="cursor-pointer"
                    onClick={() => open(s.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        open(s.id);
                      }
                    }}
                  >
                    <TableCell className="whitespace-nowrap text-muted-foreground" title={formatDateTime(s.started_at)}>{formatRelative(s.started_at)}</TableCell>
                    <TableCell>
                      <div className="font-medium">{s.agent_name}</div>
                      {s.external_providers.length > 0 && <div className="max-w-48 truncate text-[11.5px] text-warning" title={s.external_providers.join(", ")}>via {s.external_providers.join(", ")}</div>}
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground tabular md:table-cell">{duration(s.duration_s)}</TableCell>
                    <TableCell className="hidden tabular sm:table-cell">
                      {s.turn_count}
                      {s.interruptions > 0 && <span className="ml-1 text-[11.5px] text-muted-foreground">({s.interruptions} interrupted)</span>}
                    </TableCell>
                    <TableCell className="tabular">{s.response_ms_p50 != null ? formatLatency(s.response_ms_p50) : <span className="text-faint">n/a</span>}</TableCell>
                    <TableCell className="hidden lg:table-cell">
                      <Chip tone={endReason(s.end_reason).tone}>{endReason(s.end_reason).label}</Chip>
                      {s.error_count > 0 && <Chip tone="danger" className="ml-1">{s.error_count} error{s.error_count > 1 ? "s" : ""}</Chip>}
                    </TableCell>
                    <TableCell className="text-right"><Cost s={s} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {q.hasNextPage && (
              <div className="flex justify-center py-3">
                <Button variant="subtle" size="sm" disabled={q.isFetchingNextPage} onClick={() => void q.fetchNextPage()}>
                  {q.isFetchingNextPage ? "Loading..." : "Load older sessions"}
                </Button>
              </div>
            )}
          </>
        )}
      </Surface>
      <SessionDrawer id={openId} onClose={() => open(null)} />
    </>
  );
}
