"use client";

import { CheckIcon, CpuIcon, GaugeIcon, PlayIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { JobChip } from "@/components/status-chip";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldError } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAgents } from "@/features/agents/api";
import { usePermissions } from "@/features/auth/api";
import { errorMessage } from "@/lib/api/errors";
import type { Benchmark } from "@/lib/api/types";
import { languageLabel } from "@/lib/chips";
import { cn } from "@/lib/cn";
import { formatDateTime, formatLatency, formatRelative } from "@/lib/format";

import { useBenchmarkRuns, useQueueBenchmark } from "../api";

type AgentResult = NonNullable<NonNullable<Benchmark["results"]["agents"]>[string]>;

const agentResults = (run: Benchmark): AgentResult[] => Object.values(run.results.agents ?? {});

const STAGES = [
  { key: "endpoint_ms", label: "End of turn", color: "var(--stage-endpoint)" },
  { key: "stt_ms", label: "STT (parallel)", color: "var(--stage-stt)" },
  { key: "llm_first_token_ms", label: "LLM first token", color: "var(--stage-llm)" },
  { key: "tts_first_audio_ms", label: "TTS first audio", color: "var(--stage-tts)" },
] as const;

const MAX_AGENTS = 5;

function RunDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const agents = useAgents();
  const queue = useQueueBenchmark();
  const [picked, setPicked] = React.useState<string[]>([]);
  const [sessions, setSessions] = React.useState("5");
  const [error, setError] = React.useState<string | null>(null);
  const enabled = (agents.data ?? []).filter((a) => a.enabled);
  React.useEffect(() => {
    if (open) {
      setError(null);
      setPicked((p) => (p.length ? p : enabled.slice(0, 2).map((a) => a.id)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, agents.data]);

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= MAX_AGENTS ? p : [...p, id]));

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!picked.length) return setError("Pick at least one agent.");
    queue.mutate(
      { agent_ids: picked, sessions: Number(sessions) },
      {
        onSuccess: () => {
          toast.success("Benchmark queued. Results appear here as soon as the worker finishes.");
          onOpenChange(false);
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !queue.isPending && onOpenChange(o)}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Run a latency benchmark</DialogTitle>
          <DialogDescription>
            The worker calls each agent like a real caller, plays recorded questions in its language and measures every turn. Run it on a quiet machine: other load on the host slows local speech models.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogBody className="space-y-4">
            <Field label={`Agents (up to ${MAX_AGENTS})`}>
              {agents.isError ? (
                <ErrorState compact error={agents.error} onRetry={() => void agents.refetch()} />
              ) : !enabled.length && !agents.isPending ? (
                <p className="text-[13px] text-muted-foreground">Create an agent first; benchmarks compare agents.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {enabled.map((a) => {
                    const on = picked.includes(a.id);
                    return (
                      <button
                        key={a.id}
                        type="button"
                        aria-pressed={on}
                        onClick={() => toggle(a.id)}
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-full bg-muted px-3 py-1.5 text-[12.5px] font-medium transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
                          on && "bg-primary-soft text-primary",
                        )}
                      >
                        {on && <CheckIcon className="size-3.5" />}
                        {a.name}
                        <span className="text-[11px] font-normal text-muted-foreground">{languageLabel(a.language)}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </Field>
            <Field label="Conversations per agent" htmlFor="bench-sessions" hint="Each one is a full session with one question">
              <SimpleSelect
                id="bench-sessions"
                aria-label="Conversations per agent"
                value={sessions}
                onValueChange={setSessions}
                options={["3", "5", "10", "20"].map((v) => ({ value: v, label: v }))}
                className="w-32"
              />
            </Field>
            {error && <FieldError>{error}</FieldError>}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={queue.isPending || !picked.length}>
              {queue.isPending ? "Queueing..." : "Run benchmark"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AgentResultCard({ r }: { r: AgentResult }) {
  if (r.error) {
    return (
      <div className="rounded-xl bg-muted/70 px-4 py-3.5">
        <div className="text-[13px] font-semibold">{r.name ?? "Agent"}</div>
        <p className="mt-1 text-[12.5px] text-danger">{r.error}</p>
      </div>
    );
  }
  const stages = r.stages_ms_avg ?? {};
  const max = Math.max(1, ...STAGES.map((s) => stages[s.key] ?? 0));
  return (
    <div className="rounded-xl bg-muted/60 px-4 py-3.5" data-testid="bench-agent">
      <div className="flex items-baseline justify-between gap-2">
        <div className="truncate text-[13.5px] font-semibold">{r.name}</div>
        <span className="shrink-0 text-[11px] text-muted-foreground">{r.language ? languageLabel(r.language) : ""}</span>
      </div>
      <div className="mt-0.5 text-[11.5px] text-muted-foreground">
        {["stt", "llm", "tts"].map((k) => r.providers?.[k]).filter(Boolean).join(" / ")}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-[12px]">
        <div>
          <div className="text-muted-foreground">Median</div>
          <div className="text-[17px] font-semibold tabular">{r.response_ms_p50 == null ? "n/a" : formatLatency(r.response_ms_p50)}</div>
        </div>
        <div>
          <div className="text-muted-foreground">p95</div>
          <div className="text-[17px] font-semibold tabular">{r.response_ms_p95 == null ? "n/a" : formatLatency(r.response_ms_p95)}</div>
        </div>
        <div>
          <div className="text-muted-foreground" title="Measured by the benchmark client: the end of its audio to the first reply audio">Client heard</div>
          <div className="text-[17px] font-semibold tabular">{r.client_first_audio_ms_p50 == null ? "n/a" : formatLatency(r.client_first_audio_ms_p50)}</div>
        </div>
      </div>
      <dl className="mt-3 space-y-1.5 text-[11.5px]">
        {STAGES.map((s) => {
          const v = stages[s.key];
          return (
            <div key={s.key} className="grid grid-cols-[7.5rem_1fr_3.5rem] items-center gap-2">
              <dt className="text-muted-foreground">{s.label}</dt>
              <dd className="h-1.5 rounded-full bg-background/70" aria-hidden>
                <div className="h-full rounded-full" style={{ width: `${(100 * (v ?? 0)) / max}%`, background: s.color }} />
              </dd>
              <dd className="text-right tabular">{v == null ? "n/a" : formatLatency(v)}</dd>
            </div>
          );
        })}
      </dl>
      <div className="mt-2 text-[11px] text-faint">
        {r.sessions ?? 0} conversations, {r.turns ?? 0} turns
      </div>
    </div>
  );
}

function RunResults({ run }: { run: Benchmark }) {
  const rows = agentResults(run);
  const hw = run.hardware;
  return (
    <Surface>
      <SurfaceHeader
        title={`Run of ${formatDateTime(run.created_at)}`}
        titleExtra={<Hint term="responseTime" />}
        description="Response is the runtime's measure from the caller's last word to the agent's first audio"
        action={<JobChip value={run.status} />}
      />
      <div className="px-5 pb-5">
        {run.status === "failed" ? (
          <p className="text-[13px] text-danger">{run.error ?? "The run failed."}</p>
        ) : run.status !== "succeeded" ? (
          <p className="text-[13px] text-muted-foreground">
            {run.status === "running" ? "Holding conversations now. " : "Waiting for the worker. "}
            {run.config.agent_ids?.length ?? 0} agents, {run.config.sessions ?? 0} conversations each.
          </p>
        ) : (
          <>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {rows.map((r, i) => <AgentResultCard key={i} r={r} />)}
            </div>
            <p className="mt-4 inline-flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
              <CpuIcon className="size-3.5" />
              Measured on {hw.cpu ?? hw.machine ?? "unknown CPU"}, {hw.cpus ?? "?"} CPUs, GPU: {hw.gpu ?? "none"}
              {hw.load_average_1m != null && <>, load average {hw.load_average_1m}</>}. Local speech models are CPU bound; a busy host makes these numbers worse.
            </p>
          </>
        )}
      </div>
    </Surface>
  );
}

function bestMedian(run: Benchmark): number | null {
  const v = agentResults(run)
    .map((r) => r.response_ms_p50)
    .filter((x): x is number => x != null);
  return v.length ? Math.min(...v) : null;
}

export function BenchmarksScreen() {
  const runs = useBenchmarkRuns();
  const { canWrite } = usePermissions();
  const [open, setOpen] = React.useState(false);
  const [selected, setSelected] = React.useState<string | null>(null);
  const items = runs.data ?? [];
  const current = items.find((r) => r.id === selected) ?? items[0];

  return (
    <>
      <PageHeader
        title="Benchmarks"
        description="Compare agents and provider choices on the same recorded questions: response time per stage, measured for real on this machine."
        actions={
          canWrite && (
            <Button onClick={() => setOpen(true)}>
              <PlayIcon />
              Run benchmark
            </Button>
          )
        }
      />
      {runs.isPending ? (
        <Surface className="pt-3"><TableSkeleton rows={4} cols={4} /></Surface>
      ) : runs.isError && !runs.data ? (
        <Surface><ErrorState error={runs.error} onRetry={() => void runs.refetch()} /></Surface>
      ) : !current ? (
        <Surface>
          <EmptyState
            icon={GaugeIcon}
            title="No benchmarks yet"
            description="A benchmark holds real conversations with up to five agents and reports where each answer's time went, so you can pick providers on numbers."
            action={canWrite ? <Button size="sm" onClick={() => setOpen(true)}><PlayIcon />Run the first benchmark</Button> : undefined}
          />
        </Surface>
      ) : (
        <div className="space-y-4">
          <RunResults run={current} />
          <Surface className="overflow-hidden">
            <SurfaceHeader title="History" description="Select a run to see its results" />
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Agents</TableHead>
                  <TableHead className="hidden sm:table-cell">Conversations</TableHead>
                  <TableHead>Best median</TableHead>
                  <TableHead className="text-right">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((r) => {
                  const best = bestMedian(r);
                  return (
                    <TableRow
                      key={r.id}
                      tabIndex={0}
                      role="button"
                      aria-pressed={r.id === current.id}
                      aria-label={`Show benchmark from ${formatRelative(r.created_at)}`}
                      className={cn("cursor-pointer", r.id === current.id && "bg-muted/60")}
                      onClick={() => setSelected(r.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setSelected(r.id);
                        }
                      }}
                    >
                      <TableCell className="whitespace-nowrap text-muted-foreground" title={formatDateTime(r.created_at)}>{formatRelative(r.created_at)}</TableCell>
                      <TableCell className="max-w-64 truncate">
                        {agentResults(r).map((a) => a.name).filter(Boolean).join(", ") || `${r.config.agent_ids?.length ?? 0} agents`}
                      </TableCell>
                      <TableCell className="hidden tabular sm:table-cell">{r.config.sessions} each</TableCell>
                      <TableCell className="tabular">{best == null ? <span className="text-faint">n/a</span> : formatLatency(best)}</TableCell>
                      <TableCell className="text-right"><JobChip value={r.status} /></TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </Surface>
        </div>
      )}
      <RunDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
