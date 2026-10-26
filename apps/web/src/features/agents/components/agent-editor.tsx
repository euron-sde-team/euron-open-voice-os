"use client";

import { ArrowLeftIcon, ArrowRightIcon, AudioLinesIcon, SaveIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { Segmented } from "@/components/segmented";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input, Textarea } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { usePermissions } from "@/features/auth/api";
import { useProviders } from "@/features/providers/api";
import { errorMessage } from "@/lib/api/errors";
import type { Agent, AgentUpdate, Provider, ToolName } from "@/lib/api/types";
import { cn } from "@/lib/cn";

import { useAgent, useDeleteAgent, useUpdateAgent } from "../api";

const TOOLS: { name: ToolName; label: string; hint: string }[] = [
  { name: "get_current_time", label: "Current time", hint: "Answers what time it is." },
  { name: "faq_lookup", label: "FAQ lookup", hint: "Searches the FAQ below before answering." },
  { name: "end_conversation", label: "End conversation", hint: "Lets the agent say goodbye and hang up." },
  { name: "http_webhook", label: "Webhook", hint: "Posts the caller's request to one URL you set." },
];

type Form = {
  name: string;
  description: string;
  language: string;
  greeting: string;
  system_prompt: string;
  stt: string;
  llm: string;
  llm_small: string;
  tts: string;
  voice: string;
  small_words: string;
  mode: "smart" | "vad";
  vad_stop: string;
  interrupt: boolean;
  min_words: string;
  transcript_wait: string;
  tools: Set<ToolName>;
  webhook: string;
  faq: string;
  retention: string;
  redact: boolean;
  phrase_cache: boolean;
  response_cache: boolean;
  max_duration: string;
  idle: string;
  enabled: boolean;
};

function fromAgent(a: Agent): Form {
  return {
    name: a.name,
    description: a.description ?? "",
    language: a.language,
    greeting: a.greeting ?? "",
    system_prompt: a.system_prompt,
    stt: a.stt.id,
    llm: a.llm.id,
    llm_small: a.llm_small?.id ?? "",
    tts: a.tts.id,
    voice: a.voice ?? "",
    small_words: String(a.small_model_max_words),
    mode: a.turn.mode ?? "smart",
    vad_stop: String(a.turn.vad_stop_secs ?? 0.6),
    interrupt: a.turn.allow_interruptions ?? true,
    min_words: String(a.turn.interruption_min_words ?? 1),
    transcript_wait: String(a.turn.transcript_wait_s ?? 15),
    tools: new Set(a.tools.map((t) => t.name)),
    webhook: a.tools.find((t) => t.name === "http_webhook")?.url ?? "",
    faq: a.faq.join("\n"),
    retention: String(a.privacy.transcript_retention_days ?? 30),
    redact: a.privacy.redact_pii ?? true,
    phrase_cache: a.cache.tts_phrase_cache ?? true,
    response_cache: a.cache.response_cache ?? false,
    max_duration: String(a.max_duration_s),
    idle: String(a.idle_timeout_s),
    enabled: a.enabled,
  };
}

function PipelineNode({
  label,
  hint,
  value,
  onChange,
  options,
  external,
  id,
  disabled,
}: {
  label: string;
  hint: "stt" | "llm" | "tts";
  value: string;
  onChange: (v: string) => void;
  options: Provider[];
  external: boolean;
  id: string;
  disabled: boolean;
}) {
  return (
    <div className="min-w-0 flex-1 rounded-xl bg-muted/70 p-3">
      <div className="mb-1.5 flex items-center gap-1 text-[11px] font-semibold tracking-wide text-faint uppercase">
        {label}
        <Hint term={hint} />
      </div>
      <SimpleSelect
        id={id}
        value={value}
        disabled={disabled}
        onValueChange={onChange}
        options={options.map((p) => ({ value: p.id, label: `${p.name}${p.external ? " (external)" : ""}` }))}
      />
      <div className="mt-1.5 text-[11.5px]">
        {external ? <span className="text-warning">Leaves your infrastructure</span> : <span className="text-savings">Stays on your servers</span>}
      </div>
    </div>
  );
}

export function AgentEditor({ id }: { id: string }) {
  const agent = useAgent(id);
  const providers = useProviders();
  const update = useUpdateAgent();
  const remove = useDeleteAgent();
  const router = useRouter();
  const { canWrite } = usePermissions();
  const [form, setForm] = React.useState<Form | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [confirm, setConfirm] = React.useState(false);

  React.useEffect(() => {
    if (agent.data) setForm(fromAgent(agent.data));
  }, [agent.data]);

  if (agent.isError && !agent.data) {
    return (
      <>
        <PageHeader title="Agent" />
        <Surface><ErrorState error={agent.error} onRetry={() => void agent.refetch()} /></Surface>
      </>
    );
  }
  if (!agent.data || !form) {
    return (
      <>
        <PageHeader title="Agent" />
        <Skeleton className="h-[40rem] w-full rounded-2xl" />
      </>
    );
  }
  const a = agent.data;
  const all = providers.data ?? [];
  const byStage = (s: string) => all.filter((p) => p.stage === s && (p.enabled || [form.stt, form.llm, form.tts, form.llm_small].includes(p.id)));
  const isExternal = (pid: string) => all.find((p) => p.id === pid)?.external ?? false;
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => (f ? { ...f, [k]: v } : f));
  const ro = !canWrite;

  function save() {
    if (!form) return;
    const n = (v: string, fallback: number) => (Number.isFinite(Number(v)) && v.trim() ? Number(v) : fallback);
    if (form.tools.has("http_webhook") && !/^https?:\/\//.test(form.webhook.trim()))
      return setError("The webhook tool needs a URL starting with http:// or https://.");
    setError(null);
    const body: AgentUpdate = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      language: form.language.trim() || "en",
      greeting: form.greeting.trim() || null,
      system_prompt: form.system_prompt,
      stt_provider_id: form.stt,
      llm_provider_id: form.llm,
      llm_small_provider_id: form.llm_small || null,
      tts_provider_id: form.tts,
      voice: form.voice.trim() || null,
      small_model_max_words: n(form.small_words, 8),
      turn: {
        mode: form.mode,
        vad_stop_secs: n(form.vad_stop, 0.6),
        allow_interruptions: form.interrupt,
        interruption_min_words: n(form.min_words, 1),
        transcript_wait_s: n(form.transcript_wait, 15),
      },
      privacy: { transcript_retention_days: n(form.retention, 30), redact_pii: form.redact },
      cache: { tts_phrase_cache: form.phrase_cache, response_cache: form.response_cache && form.tools.size === 0 },
      tools: [...form.tools].map((name) => (name === "http_webhook" ? { name, url: form.webhook.trim() } : { name })),
      faq: form.faq.split("\n").map((l) => l.trim()).filter(Boolean),
      max_duration_s: n(form.max_duration, 900),
      idle_timeout_s: n(form.idle, 60),
      enabled: form.enabled,
    };
    update.mutate(
      { id, body },
      {
        onSuccess: (saved) => toast.success(`Saved. ${saved.name} is now version ${saved.version}; the next session uses it.`),
        onError: (e) => setError(errorMessage(e)),
      },
    );
  }

  return (
    <>
      <div className="mb-2">
        <Link href="/agents" className="inline-flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground">
          <ArrowLeftIcon className="size-3.5" />
          Agents
        </Link>
      </div>
      <PageHeader
        title={a.name}
        description={`Version ${a.version}. Changes apply to the next session.`}
        actions={
          <div className="flex gap-2">
            <Button variant="outline" nativeButton={false} render={<Link href={`/talk?agent=${a.id}`} />}>
              <AudioLinesIcon />
              Talk
            </Button>
            {canWrite && (
              <Button onClick={save} disabled={update.isPending}>
                <SaveIcon />
                {update.isPending ? "Saving..." : "Save"}
              </Button>
            )}
          </div>
        }
      />
      {error && <FieldError className="mb-3">{error}</FieldError>}
      <div className="space-y-4">
        <Surface>
          <SurfaceHeader title="Pipeline" description="What this agent listens, thinks and speaks with" />
          <div className="flex flex-col items-stretch gap-2 px-5 pb-5 md:flex-row md:items-center">
            <PipelineNode id="a-stt" label="Listens" hint="stt" value={form.stt} onChange={(v) => set("stt", v)} options={byStage("stt")} external={isExternal(form.stt)} disabled={ro} />
            <ArrowRightIcon className="hidden size-4 shrink-0 text-faint md:block" />
            <PipelineNode id="a-llm" label="Thinks" hint="llm" value={form.llm} onChange={(v) => set("llm", v)} options={byStage("llm")} external={isExternal(form.llm)} disabled={ro} />
            <ArrowRightIcon className="hidden size-4 shrink-0 text-faint md:block" />
            <PipelineNode id="a-tts" label="Speaks" hint="tts" value={form.tts} onChange={(v) => set("tts", v)} options={byStage("tts")} external={isExternal(form.tts)} disabled={ro} />
          </div>
          <div className="grid gap-3 px-5 pb-5 sm:grid-cols-3">
            <Field label="Voice" htmlFor="a-voice" hint="Empty: the TTS provider's voice">
              <Input id="a-voice" value={form.voice} disabled={ro} onChange={(e) => set("voice", e.target.value)} className="font-mono" placeholder="af_heart" />
            </Field>
            <Field label="Language" htmlFor="a-lang" hint="en, hi, mr, ...">
              <Input id="a-lang" value={form.language} disabled={ro} onChange={(e) => set("language", e.target.value)} />
            </Field>
            <Field label={<span className="inline-flex items-center gap-1">Small model <Hint term="smallModel" /></span>} htmlFor="a-small">
              <SimpleSelect
                id="a-small"
                value={form.llm_small || "none"}
                disabled={ro}
                onValueChange={(v) => set("llm_small", v === "none" ? "" : v)}
                options={[{ value: "none", label: "None" }, ...byStage("llm").filter((p) => p.id !== form.llm).map((p) => ({ value: p.id, label: p.name }))]}
              />
            </Field>
          </div>
        </Surface>

        <Surface>
          <SurfaceHeader title="What it says" />
          <div className="space-y-4 px-5 pb-5">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name" htmlFor="a-name">
                <Input id="a-name" value={form.name} disabled={ro} onChange={(e) => set("name", e.target.value)} />
              </Field>
              <Field label="Greeting" htmlFor="a-greeting" hint="Spoken first; empty lets the model open">
                <Input id="a-greeting" value={form.greeting} disabled={ro} onChange={(e) => set("greeting", e.target.value)} />
              </Field>
            </div>
            <Field label="Instructions" htmlFor="a-prompt" hint="The system prompt. Answers are spoken: ask for short sentences and no formatting.">
              <Textarea id="a-prompt" value={form.system_prompt} disabled={ro} onChange={(e) => set("system_prompt", e.target.value)} rows={6} />
            </Field>
            <Field label="Description" htmlFor="a-desc">
              <Input id="a-desc" value={form.description} disabled={ro} onChange={(e) => set("description", e.target.value)} />
            </Field>
          </div>
        </Surface>

        <div className="grid gap-4 lg:grid-cols-2">
          <Surface>
            <SurfaceHeader title="Conversation" description="How it takes turns" />
            <div className="space-y-4 px-5 pb-5">
              <Field label="End of turn">
                <Segmented<"smart" | "vad">
                  ariaLabel="End of turn"
                  value={form.mode}
                  onChange={(v) => set("mode", v)}
                  options={[{ value: "smart", label: "Smart turn" }, { value: "vad", label: "Silence only" }]}
                />
              </Field>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Pause" htmlFor="a-vad" hint="seconds">
                  <Input id="a-vad" inputMode="decimal" value={form.vad_stop} disabled={ro} onChange={(e) => set("vad_stop", e.target.value)} className="tabular" />
                </Field>
                <Field label="Interrupt after" htmlFor="a-minw" hint="words">
                  <Input id="a-minw" inputMode="numeric" value={form.min_words} disabled={ro || !form.interrupt} onChange={(e) => set("min_words", e.target.value)} className="tabular" />
                </Field>
                <Field label="Transcript wait" htmlFor="a-tw" hint="seconds">
                  <Input id="a-tw" inputMode="decimal" value={form.transcript_wait} disabled={ro} onChange={(e) => set("transcript_wait", e.target.value)} className="tabular" />
                </Field>
              </div>
              <label className="flex items-center gap-2 text-[13px]">
                <Switch checked={form.interrupt} disabled={ro} onCheckedChange={(v) => set("interrupt", v)} aria-label="Allow interruptions" />
                Callers can interrupt the agent <Hint term="interruption" />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Longest call" htmlFor="a-max" hint="seconds">
                  <Input id="a-max" inputMode="numeric" value={form.max_duration} disabled={ro} onChange={(e) => set("max_duration", e.target.value)} className="tabular" />
                </Field>
                <Field label="Hang up after silence" htmlFor="a-idle" hint="seconds">
                  <Input id="a-idle" inputMode="numeric" value={form.idle} disabled={ro} onChange={(e) => set("idle", e.target.value)} className="tabular" />
                </Field>
              </div>
            </div>
          </Surface>

          <Surface>
            <SurfaceHeader title="Privacy and cost" />
            <div className="space-y-4 px-5 pb-5">
              <Field label={<span className="inline-flex items-center gap-1">Keep transcripts for <Hint term="retention" /></span>} htmlFor="a-ret" hint="days; 0 = never store words">
                <Input id="a-ret" inputMode="numeric" value={form.retention} disabled={ro} onChange={(e) => set("retention", e.target.value)} className="tabular" />
              </Field>
              <label className="flex items-center gap-2 text-[13px]">
                <Switch checked={form.redact} disabled={ro} onCheckedChange={(v) => set("redact", v)} aria-label="Redact personal details" />
                Redact emails, phone, card, Aadhaar and PAN numbers before storing
              </label>
              <p className="text-[12px] text-muted-foreground">Audio is never stored.</p>
              <label className="flex items-center gap-2 text-[13px]">
                <Switch checked={form.phrase_cache} disabled={ro} onCheckedChange={(v) => set("phrase_cache", v)} aria-label="Phrase cache" />
                Reuse audio for repeated phrases <Hint term="phraseCache" />
              </label>
              <label className={cn("flex items-center gap-2 text-[13px]", form.tools.size > 0 && "opacity-60")}>
                <Switch checked={form.response_cache && form.tools.size === 0} disabled={ro || form.tools.size > 0} onCheckedChange={(v) => set("response_cache", v)} aria-label="Response cache" />
                Answer exact repeats from cache <Hint term="responseCache" />
                {form.tools.size > 0 && <span className="text-[11.5px] text-muted-foreground">(not with tools)</span>}
              </label>
              {form.llm_small && (
                <Field label="Small model for turns up to" htmlFor="a-sw" hint="words">
                  <Input id="a-sw" inputMode="numeric" value={form.small_words} disabled={ro} onChange={(e) => set("small_words", e.target.value)} className="tabular" />
                </Field>
              )}
            </div>
          </Surface>
        </div>

        <Surface>
          <SurfaceHeader title="Tools and knowledge" description="What the agent can do besides talking" />
          <div className="grid gap-4 px-5 pb-5 lg:grid-cols-2">
            <div className="space-y-2.5">
              {TOOLS.map((t) => (
                <label key={t.name} className="flex items-start gap-2 text-[13px]">
                  <Switch
                    checked={form.tools.has(t.name)}
                    disabled={ro}
                    aria-label={t.label}
                    onCheckedChange={(on) => {
                      const next = new Set(form.tools);
                      if (on) next.add(t.name);
                      else next.delete(t.name);
                      set("tools", next);
                    }}
                  />
                  <span>
                    {t.label}
                    <span className="block text-[12px] text-muted-foreground">{t.hint}</span>
                  </span>
                </label>
              ))}
              {form.tools.has("http_webhook") && (
                <Field label="Webhook URL" htmlFor="a-hook">
                  <Input id="a-hook" value={form.webhook} disabled={ro} onChange={(e) => set("webhook", e.target.value)} className="font-mono" placeholder="https://example.com/voice-requests" />
                </Field>
              )}
            </div>
            <Field label="FAQ" htmlFor="a-faq" hint="One answer per line. The FAQ lookup tool searches these.">
              <Textarea id="a-faq" value={form.faq} disabled={ro} onChange={(e) => set("faq", e.target.value)} rows={7} />
            </Field>
          </div>
        </Surface>

        {canWrite && (
          <Surface>
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
              <label className="flex items-center gap-2 text-[13px]">
                <Switch checked={form.enabled} onCheckedChange={(v) => set("enabled", v)} aria-label="Agent enabled" />
                Enabled: new sessions can start
              </label>
              <div className="flex items-center gap-2">
                {a.external_providers.length > 0 && <Chip tone="warning">Sends data to {a.external_providers.join(", ")}</Chip>}
                <Button variant="destructive-soft" size="sm" onClick={() => setConfirm(true)}>
                  <Trash2Icon />
                  Delete agent
                </Button>
              </div>
            </div>
          </Surface>
        )}
      </div>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={`Delete ${a.name}?`}
        description="Its past sessions stay in history. SDK keys scoped to it lose access to it."
        confirmLabel="Delete agent"
        pending={remove.isPending}
        onConfirm={() =>
          remove.mutate(a.id, {
            onSuccess: () => {
              toast.success(`${a.name} deleted.`);
              router.push("/agents");
            },
            onError: (e) => toast.error(errorMessage(e)),
          })
        }
      />
    </>
  );
}
