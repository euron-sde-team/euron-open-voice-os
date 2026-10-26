"use client";

import { AudioLinesIcon, ClockIcon, CoinsIcon, GlobeIcon, MessagesSquareIcon, PiggyBankIcon, TimerIcon, ZapOffIcon } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { KpiTile } from "@/components/kpi-tile";
import { PageHeader } from "@/components/page-header";
import { Segmented } from "@/components/segmented";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { AgentBreakdown, Overview, StageLatency } from "@/lib/api/types";
import type { GlossaryKey } from "@/lib/glossary";
import { formatLatency, formatNumber, formatPercent, formatUsd } from "@/lib/format";
import { DAY_OPTIONS, useUiPrefs, type Days } from "@/lib/store";

import { useOverview } from "../api";

const ActivityChart = dynamic(() => import("./activity-chart"), {
  ssr: false,
  loading: () => <Skeleton className="h-[290px] w-full" />,
});

const STAGES: { key: keyof StageLatency; label: string; color: string; hint: GlossaryKey }[] = [
  { key: "endpoint_ms", label: "End of turn", color: "var(--stage-endpoint)", hint: "endpoint" },
  { key: "stt_ms", label: "Speech to text (parallel)", color: "var(--stage-stt)", hint: "stt" },
  { key: "llm_first_token_ms", label: "LLM first token", color: "var(--stage-llm)", hint: "llm" },
  { key: "tts_first_audio_ms", label: "TTS first audio", color: "var(--stage-tts)", hint: "tts" },
];

function StageBreakdown({ stages }: { stages: StageLatency }) {
  const max = Math.max(1, ...STAGES.map((s) => stages[s.key] ?? 0));
  if (STAGES.every((s) => stages[s.key] == null)) {
    return <p className="px-5 pb-5 text-[13px] text-muted-foreground">Stage timings appear once a turn has been answered.</p>;
  }
  return (
    <ul className="space-y-3.5 px-5 pb-5">
      {STAGES.map((s) => {
        const v = stages[s.key];
        return (
          <li key={s.key}>
            <div className="mb-1 flex items-baseline justify-between gap-3 text-[13px]">
              <span className="inline-flex items-center gap-1 font-medium">
                {s.label}
                <Hint term={s.hint} />
              </span>
              <span className="text-muted-foreground tabular">{v == null ? "n/a" : formatLatency(v)}</span>
            </div>
            <div className="h-2 rounded-full bg-muted" aria-hidden>
              <div className="h-full rounded-full" style={{ width: `${(100 * (v ?? 0)) / max}%`, background: s.color }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function ByAgent({ rows }: { rows: AgentBreakdown[] }) {
  if (!rows.length) return <p className="px-5 pb-5 text-[13px] text-muted-foreground">No sessions in this period yet.</p>;
  return (
    <ul className="divide-y divide-hairline px-5 pb-3">
      {rows.map((r) => (
        <li key={r.agent_key} className="grid grid-cols-[1fr_auto] items-center gap-3 py-2.5">
          <div className="min-w-0">
            <div className="truncate text-[13px] font-medium">{r.agent_name}</div>
            <div className="text-[11.5px] text-muted-foreground tabular">
              {formatNumber(r.sessions)} sessions, {formatNumber(r.minutes)} min
            </div>
          </div>
          <div className="text-right text-[12px] text-muted-foreground tabular">
            <div className="font-semibold text-foreground">{r.response_ms_avg == null ? "n/a" : formatLatency(r.response_ms_avg)}</div>
            {r.cost_per_session_usd == null ? "no list price" : `${formatUsd(r.cost_per_session_usd)} / session`}
          </div>
        </li>
      ))}
    </ul>
  );
}

function Kpis({ data, days }: { data: Overview | undefined; days: number }) {
  const p = data?.previous ?? {};
  const cmp = `vs previous ${days === 1 ? "24 hours" : `${days} days`}`;
  const loading = !data;
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <KpiTile
        label="Response, median"
        icon={TimerIcon}
        hint="responseTime"
        value={formatLatency(data?.response_ms_p50)}
        current={data?.response_ms_avg ?? undefined}
        previous={p.response_ms_avg || undefined}
        goodWhen="down"
        comparison={`p95 ${formatLatency(data?.response_ms_p95)}; change is in the average`}
        accent="primary"
        loading={loading}
      />
      <KpiTile
        label="Sessions"
        icon={MessagesSquareIcon}
        value={formatNumber(data?.sessions)}
        current={data?.sessions}
        previous={p.sessions}
        goodWhen="neutral"
        comparison={cmp}
        loading={loading}
      />
      <KpiTile
        label="Minutes talked"
        icon={ClockIcon}
        value={formatNumber(data?.minutes)}
        current={data?.minutes}
        previous={p.minutes}
        goodWhen="neutral"
        comparison={cmp}
        loading={loading}
      />
      <KpiTile
        label="Cost (est.)"
        icon={CoinsIcon}
        hint="cost"
        value={formatUsd(data?.cost_usd)}
        current={data?.cost_usd}
        previous={p.cost_usd}
        goodWhen="down"
        comparison={data?.cost_per_session_usd != null ? `${formatUsd(data.cost_per_session_usd)} per costed session` : cmp}
        accent="warning"
        loading={loading}
      />
      <KpiTile
        label="Saved by caches"
        icon={PiggyBankIcon}
        hint="savings"
        value={formatUsd(data?.savings_usd)}
        comparison={data ? `${formatNumber(data.response_cache_hits)} cached answers, ${formatNumber(data.tts_characters_cached)} characters replayed` : ""}
        accent="savings"
        loading={loading}
      />
      <KpiTile
        label="Interruptions"
        icon={ZapOffIcon}
        hint="interruption"
        value={formatPercent(data ? data.interruption_rate * 100 : undefined)}
        comparison={data ? `of ${formatNumber(data.turns)} turns` : ""}
        loading={loading}
      />
      <KpiTile
        label="Used external providers"
        icon={GlobeIcon}
        hint="external"
        value={formatNumber(data?.external_sessions)}
        comparison={data ? `of ${formatNumber(data.sessions)} sessions` : ""}
        loading={loading}
      />
      <KpiTile
        label="Sessions with errors"
        icon={AudioLinesIcon}
        value={formatNumber(data?.error_sessions)}
        comparison={data?.error_sessions ? "Filter Sessions by errors to see why" : "None in this period"}
        accent={data?.error_sessions ? "warning" : undefined}
        loading={loading}
      />
    </div>
  );
}

export function OverviewScreen() {
  const days = useUiPrefs((s) => s.days);
  const setDays = useUiPrefs((s) => s.setDays);
  const overview = useOverview(days);
  const data = overview.data;

  const header = (
    <PageHeader
      title="Overview"
      description="How fast your agents answer, where the time goes, and what each conversation costs."
      actions={
        <Segmented<string>
          ariaLabel="Period"
          value={String(days)}
          onChange={(v) => setDays(Number(v) as Days)}
          options={DAY_OPTIONS.map((d) => ({ value: String(d), label: d === 1 ? "24h" : `${d}d` }))}
          className="w-48"
        />
      }
    />
  );

  if (overview.isError && !data) {
    return (
      <>
        {header}
        <Surface>
          <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
        </Surface>
      </>
    );
  }

  if (data && data.sessions === 0 && (data.previous.sessions ?? 0) === 0) {
    return (
      <>
        {header}
        <Surface>
          <EmptyState
            icon={AudioLinesIcon}
            title="No conversations yet"
            description="Every session, from the Talk page or the SDK, is recorded here with its response time per stage, usage and estimated cost. Say hello to an agent to see it work."
            action={
              <Button nativeButton={false} render={<Link href="/talk" />}>
                <AudioLinesIcon />
                Talk to an agent
              </Button>
            }
          />
        </Surface>
      </>
    );
  }

  return (
    <>
      {header}
      <div className="space-y-4">
        <Kpis data={data} days={days} />
        <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <Surface className="flex flex-col">
            <SurfaceHeader
              title="Sessions and response time"
              titleExtra={<Hint term="responseTime" />}
              description="Bars count conversations; the line is the average time to the agent's first audio"
            />
            <div className="flex flex-1 px-5 pb-5">
              {data ? <ActivityChart points={data.series} hourly={days === 1} /> : <Skeleton className="h-[290px] w-full" />}
            </div>
          </Surface>
          <Surface>
            <SurfaceHeader title="Where the time goes" description="Average per stage across the period's turns" />
            {data ? <StageBreakdown stages={data.stages} /> : <Skeleton className="mx-5 mb-5 h-40" />}
          </Surface>
        </div>
        <Surface>
          <SurfaceHeader
            title="By agent"
            description="Response time and cost per session"
            action={
              <Button variant="subtle" size="xs" nativeButton={false} render={<Link href="/sessions" />}>
                All sessions
              </Button>
            }
          />
          {data ? <ByAgent rows={data.by_agent} /> : <Skeleton className="mx-5 mb-5 h-32" />}
        </Surface>
      </div>
    </>
  );
}
