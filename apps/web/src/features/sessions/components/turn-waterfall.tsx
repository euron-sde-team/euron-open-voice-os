"use client";

import type { Turn } from "@/lib/api/types";
import { formatLatency } from "@/lib/format";

const STAGES = [
  { key: "endpoint_ms", label: "End of turn", color: "var(--stage-endpoint)" },
  { key: "llm_first_token_ms", label: "LLM first token", color: "var(--stage-llm)" },
  { key: "tts_first_audio_ms", label: "TTS first audio", color: "var(--stage-tts)" },
] as const;

/**
 * Where one turn's response time went: end-of-turn detection, the language model's first
 * token, then synthesis to first audio, in sequence. Speech recognition runs in parallel
 * with end-of-turn detection, so it is drawn on its own line under the same scale.
 */
export function TurnWaterfall({ turn, scaleMs }: { turn: Turn; scaleMs: number }) {
  const total = turn.response_ms;
  if (total == null) return null;
  const pct = (v: number | null | undefined) => `${Math.max(0, Math.min(100, ((v ?? 0) / scaleMs) * 100))}%`;
  const parts = STAGES.map((s) => ({ ...s, value: turn[s.key] }));
  const known = parts.reduce((acc, p) => acc + (p.value ?? 0), 0);
  const other = Math.max(0, total - known);
  return (
    <div className="space-y-1" data-testid="waterfall">
      <div className="flex h-2.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`Response ${formatLatency(total)}`}>
        {parts.map((p) =>
          p.value ? <div key={p.key} style={{ width: pct(p.value), background: p.color }} title={`${p.label}: ${formatLatency(p.value)}`} /> : null,
        )}
        {other > 1 && <div style={{ width: pct(other), background: "var(--faint)" }} title={`Transport and playout: ${formatLatency(other)}`} />}
      </div>
      {turn.stt_ms != null && (
        <div className="flex h-1.5 overflow-hidden rounded-full">
          <div style={{ width: pct(turn.stt_ms), background: "var(--stage-stt)" }} title={`Speech to text (in parallel): ${formatLatency(turn.stt_ms)}`} />
        </div>
      )}
    </div>
  );
}

export function WaterfallLegend() {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-muted-foreground">
      {[...STAGES, { key: "stt", label: "Speech to text (parallel)", color: "var(--stage-stt)" }].map((s) => (
        <span key={s.key} className="inline-flex items-center gap-1.5">
          <span className="size-2 rounded-full" style={{ background: s.color }} />
          {s.label}
        </span>
      ))}
    </div>
  );
}
