"use client";

import * as React from "react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { CHART, ChartLegend, ChartTooltipCard } from "@/components/charts/chart-tooltip";
import type { Point } from "@/lib/api/types";
import { formatLatency, formatNumber, formatUsd } from "@/lib/format";

const axisProps = {
  stroke: CHART.axis,
  tick: { fill: CHART.axis, fontSize: 11 },
  tickLine: false,
  axisLine: false,
} as const;

const dayFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const hourFmt = new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
const longFmt = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** Sessions per bucket as bars, with the average response time as a line on its own axis. */
export default function ActivityChart({ points, hourly }: { points: Point[]; hourly: boolean }) {
  const sessions = points.reduce((a, p) => a + p.sessions, 0);
  const timed = points.filter((p) => p.response_ms_avg != null);
  const avg = timed.length ? timed.reduce((a, p) => a + (p.response_ms_avg ?? 0) * p.sessions, 0) / Math.max(1, timed.reduce((a, p) => a + p.sessions, 0)) : null;
  const ticks = React.useMemo(() => {
    const step = Math.max(1, Math.ceil(points.length / 7));
    return points.filter((_, i) => i % step === 0).map((p) => p.t);
  }, [points]);
  const fmt = (t: string) => (hourly ? hourFmt : dayFmt).format(new Date(t));

  return (
    <div className="flex flex-1 flex-col gap-3">
      <ChartLegend
        items={[
          { label: "Sessions", color: CHART.before, value: formatNumber(sessions) },
          { label: "Avg response", color: CHART.after, value: avg == null ? "n/a" : formatLatency(avg) },
        ]}
      />
      <div className="min-h-[260px] w-full flex-1" role="img" aria-label="Sessions and average response time over time">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} margin={{ top: 6, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={CHART.grid} />
            <XAxis dataKey="t" ticks={ticks} tickFormatter={fmt} {...axisProps} minTickGap={16} />
            <YAxis yAxisId="s" allowDecimals={false} width={36} {...axisProps} />
            <YAxis yAxisId="ms" orientation="right" width={52} tickFormatter={(v: number) => formatLatency(v)} {...axisProps} />
            <Tooltip
              cursor={{ fill: "var(--muted)", opacity: 0.5 }}
              content={({ active, payload }) => {
                const row = payload?.[0]?.payload as Point | undefined;
                if (!active || !row) return null;
                return (
                  <ChartTooltipCard
                    title={longFmt.format(new Date(row.t))}
                    rows={[
                      { label: "Sessions", value: formatNumber(row.sessions), color: CHART.before },
                      { label: "Avg response", value: row.response_ms_avg == null ? "n/a" : formatLatency(row.response_ms_avg), color: CHART.after },
                    ]}
                    footer={`${formatNumber(row.minutes)} min talked, ${formatUsd(row.cost_usd)} estimated`}
                  />
                );
              }}
            />
            <Bar yAxisId="s" dataKey="sessions" fill={CHART.before} radius={[3, 3, 0, 0]} maxBarSize={22} />
            <Line
              yAxisId="ms"
              type="monotone"
              dataKey="response_ms_avg"
              stroke={CHART.after}
              strokeWidth={2}
              dot={false}
              connectNulls
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
