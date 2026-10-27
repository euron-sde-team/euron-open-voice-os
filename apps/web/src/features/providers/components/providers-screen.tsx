"use client";

import { CableIcon, PencilIcon, PlugIcon, PlusIcon, Trash2Icon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { usePermissions } from "@/features/auth/api";
import { errorMessage } from "@/lib/api/errors";
import type { Adapter, Price, Provider, Stage } from "@/lib/api/types";
import { ADAPTERS_BY_STAGE, adapterLabel, stageLabel } from "@/lib/chips";
import { cn } from "@/lib/cn";

import { useCreateProvider, useDeleteProvider, useProviders, useTestProvider, useUpdateProvider } from "../api";

const STAGES: Stage[] = ["stt", "llm", "tts"];
const NEEDS_URL = new Set(["openai_compatible", "mock"]);
const URL_HINT: Record<string, string> = {
  stt: "e.g. http://speech:8080/v1 (VoiceOS local Whisper) or https://api.openai.com/v1",
  llm: "e.g. http://ollama:11434/v1, https://api.openai.com/v1, or a TokenShield or SmartRouter URL",
  tts: "e.g. http://speech:8080/v1 (VoiceOS local Kokoro)",
};

function priceText(stage: string, price: Price): string | null {
  if (stage === "stt" && price.per_audio_minute != null) return `$${price.per_audio_minute} / audio minute`;
  if (stage === "llm" && price.per_million_input_tokens != null)
    return `$${price.per_million_input_tokens} in, $${price.per_million_output_tokens ?? "?"} out / 1M tokens`;
  if (stage === "tts" && price.per_million_characters != null) return `$${price.per_million_characters} / 1M characters`;
  return null;
}

function num(v: string): number | null {
  const n = Number(v);
  return v.trim() && Number.isFinite(n) && n >= 0 ? n : null;
}

function ProviderDialog({
  open,
  onOpenChange,
  provider,
  stage: initialStage,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  provider: Provider | null;
  stage: Stage;
}) {
  const create = useCreateProvider();
  const update = useUpdateProvider();
  const editing = provider != null;
  const pending = create.isPending || update.isPending;
  const [stage, setStage] = React.useState<Stage>(initialStage);
  const [adapter, setAdapter] = React.useState<Adapter>("openai_compatible");
  const [name, setName] = React.useState("");
  const [url, setUrl] = React.useState("");
  const [model, setModel] = React.useState("");
  const [voice, setVoice] = React.useState("");
  const [language, setLanguage] = React.useState("");
  const [key, setKey] = React.useState("");
  const [clearKey, setClearKey] = React.useState(false);
  const [external, setExternal] = React.useState(false);
  const [timeout, setTimeoutS] = React.useState("15");
  const [p1, setP1] = React.useState("");
  const [p2, setP2] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    const pr = provider;
    setStage((pr?.stage as Stage) ?? initialStage);
    setAdapter((pr?.adapter as Adapter) ?? "openai_compatible");
    setName(pr?.name ?? "");
    setUrl(pr?.base_url ?? "");
    setModel(pr?.model ?? "");
    setVoice(pr?.voice ?? "");
    setLanguage(pr?.language ?? "");
    setKey("");
    setClearKey(false);
    setExternal(Boolean(pr?.external && pr?.self_hosted === false && pr?.adapter === "openai_compatible"));
    setTimeoutS(String(pr?.timeout_s ?? 15));
    const price = pr?.price ?? {};
    const s = (pr?.stage as Stage) ?? initialStage;
    setP1(String((s === "stt" ? price.per_audio_minute : s === "llm" ? price.per_million_input_tokens : price.per_million_characters) ?? ""));
    setP2(String(price.per_million_output_tokens ?? ""));
    setError(null);
  }, [open, provider, initialStage]);

  function priceBody(): Price {
    if (stage === "stt") return { per_audio_minute: num(p1) };
    if (stage === "llm") return { per_million_input_tokens: num(p1), per_million_output_tokens: num(p2) };
    return { per_million_characters: num(p1) };
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("Give the provider a name people will recognize, for example \"Local Whisper\".");
    if (NEEDS_URL.has(adapter) && !/^https?:\/\//.test(url.trim()))
      return setError("The base URL starts with http:// or https:// and usually ends in /v1.");
    const t = Number(timeout);
    if (!Number.isFinite(t) || t <= 0 || t > 120) return setError("The timeout is between 1 and 120 seconds.");
    setError(null);
    const done = {
      onSuccess: () => {
        toast.success(editing ? "Provider saved." : "Provider added.");
        onOpenChange(false);
      },
      onError: (err: unknown) => setError(errorMessage(err)),
    };
    const common = {
      name: name.trim(),
      base_url: url.trim() || null,
      model: model.trim() || null,
      voice: voice.trim() || null,
      language: language.trim() || null,
      timeout_s: t,
      price: priceBody(),
      external,
    };
    if (editing && provider) {
      update.mutate(
        { id: provider.id, body: { ...common, ...(key ? { api_key: key } : clearKey ? { clear_api_key: true } : {}) } },
        done,
      );
    } else {
      create.mutate({ ...common, stage, adapter, api_key: key || null, enabled: true }, done);
    }
  }

  const unit = stage === "stt" ? "USD per audio minute" : stage === "llm" ? "USD per 1M input tokens" : "USD per 1M characters";
  return (
    <Dialog open={open} onOpenChange={(o) => !pending && onOpenChange(o)}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? `Edit ${provider?.name}` : `Add a ${stageLabel(stage).toLowerCase()} provider`}</DialogTitle>
          <DialogDescription>API keys are sealed at rest and never shown again. Prices are only used to estimate cost.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogBody className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Stage" htmlFor="p-stage">
                <SimpleSelect
                  id="p-stage"
                  value={stage}
                  disabled={editing}
                  onValueChange={(v) => {
                    setStage(v as Stage);
                    if (!ADAPTERS_BY_STAGE[v]?.includes(adapter)) setAdapter("openai_compatible");
                  }}
                  options={STAGES.map((s) => ({ value: s, label: stageLabel(s) }))}
                />
              </Field>
              <Field label="Adapter" htmlFor="p-adapter">
                <SimpleSelect
                  id="p-adapter"
                  value={adapter}
                  disabled={editing}
                  onValueChange={(v) => setAdapter(v as Adapter)}
                  options={(ADAPTERS_BY_STAGE[stage] ?? []).map((a) => ({ value: a, label: adapterLabel(a) }))}
                />
              </Field>
            </div>
            <Field label="Name" htmlFor="p-name">
              <Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Local Whisper" />
            </Field>
            {NEEDS_URL.has(adapter) && (
              <Field label="Base URL" htmlFor="p-url" hint={URL_HINT[stage]}>
                <Input id="p-url" value={url} onChange={(e) => setUrl(e.target.value)} className="font-mono" placeholder="http://speech:8080/v1" />
              </Field>
            )}
            <div className="grid grid-cols-2 gap-3">
              <Field label="Model" htmlFor="p-model" hint={stage === "stt" ? "whisper-base, nova-3, ..." : stage === "llm" ? "gpt-4o-mini, llama3.2, ..." : "kokoro, eleven_flash_v2_5, ..."}>
                <Input id="p-model" value={model} onChange={(e) => setModel(e.target.value)} className="font-mono" />
              </Field>
              {stage === "tts" ? (
                <Field label="Voice" htmlFor="p-voice" hint="af_heart, hf_alpha (Hindi), ...">
                  <Input id="p-voice" value={voice} onChange={(e) => setVoice(e.target.value)} className="font-mono" />
                </Field>
              ) : (
                <Field label="Language" htmlFor="p-lang" hint="Empty: the agent's language">
                  <Input id="p-lang" value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="en" />
                </Field>
              )}
            </div>
            <Field label="API key" htmlFor="p-key" hint={editing && provider?.has_api_key ? `Stored (${provider.key_hint}). Leave empty to keep it.` : "Optional for self-hosted servers"}>
              <Input id="p-key" type="password" value={key} disabled={clearKey} onChange={(e) => setKey(e.target.value)} autoComplete="off" />
            </Field>
            {editing && provider?.has_api_key && (
              <label className="flex items-center gap-2 text-[13px]">
                <Switch checked={clearKey} onCheckedChange={(v) => { setClearKey(v); if (v) setKey(""); }} aria-label="Remove stored key" />
                Remove the stored key
              </label>
            )}
            <div className={cn("grid gap-3", stage === "llm" ? "grid-cols-3" : "grid-cols-2")}>
              <Field label="Price" htmlFor="p-price" hint={unit}>
                <Input id="p-price" inputMode="decimal" value={p1} onChange={(e) => setP1(e.target.value)} className="tabular" placeholder="Not set" />
              </Field>
              {stage === "llm" && (
                <Field label="Output price" htmlFor="p-price2" hint="per 1M output tokens">
                  <Input id="p-price2" inputMode="decimal" value={p2} onChange={(e) => setP2(e.target.value)} className="tabular" placeholder="Not set" />
                </Field>
              )}
              <Field label="Timeout" htmlFor="p-timeout" hint="seconds">
                <Input id="p-timeout" inputMode="numeric" value={timeout} onChange={(e) => setTimeoutS(e.target.value)} className="tabular" />
              </Field>
            </div>
            {adapter === "openai_compatible" && (
              <label className="flex items-start gap-2 text-[13px]">
                <Switch checked={external} onCheckedChange={setExternal} aria-label="Treat as external" />
                <span>
                  Treat as external
                  <span className="block text-[12px] text-muted-foreground">
                    A public URL is always external. Mark a private one too if it forwards audio or text elsewhere.
                  </span>
                </span>
              </label>
            )}
            {error && <FieldError>{error}</FieldError>}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? "Saving..." : editing ? "Save" : "Add provider"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ProviderRow({ p, canWrite, onEdit, onDelete }: { p: Provider; canWrite: boolean; onEdit: () => void; onDelete: () => void }) {
  const test = useTestProvider();
  const price = priceText(p.stage, p.price);
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5" data-testid="provider-row">
      <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{p.name}</span>
          {p.external ? (
            <Chip tone="warning" title="Audio or text leaves your infrastructure">External</Chip>
          ) : p.self_hosted ? (
            <Chip tone="savings">Self-hosted</Chip>
          ) : (
            <Chip tone="neutral">Mock</Chip>
          )}
          {!p.enabled && <Chip tone="neutral">Disabled</Chip>}
        </div>
        <div className="mt-0.5 truncate text-[12px] text-muted-foreground">
          {adapterLabel(p.adapter)}
          {p.model && <> &middot; <span className="font-mono">{p.model}</span></>}
          {p.voice && <> &middot; voice <span className="font-mono">{p.voice}</span></>}
          {p.base_url && <> &middot; <span className="font-mono">{p.base_url}</span></>}
        </div>
      </div>
      <div className="text-[12px] text-muted-foreground sm:text-right">
        <div>{p.self_hosted ? "No per-call price" : price ?? "No price set"}</div>
        <div>{p.used_by ? `Used by ${p.used_by} agent${p.used_by === 1 ? "" : "s"}` : "Not used yet"}</div>
      </div>
      {canWrite && (
        <div className="flex gap-1">
          <Button
            variant="subtle"
            size="xs"
            disabled={test.isPending}
            aria-label={`Test ${p.name}`}
            onClick={() =>
              test.mutate(p.id, {
                onSuccess: (r) => (r.ok ? toast.success(`${p.name}: ${r.message}${r.latency_ms != null ? ` (${Math.round(r.latency_ms)} ms)` : ""}`) : toast.error(`${p.name}: ${r.message}`)),
                onError: (e) => toast.error(errorMessage(e)),
              })
            }
          >
            <PlugIcon />
            {test.isPending ? "Testing..." : "Test"}
          </Button>
          <Button variant="subtle" size="icon-xs" aria-label={`Edit ${p.name}`} onClick={onEdit}>
            <PencilIcon />
          </Button>
          <Button variant="subtle" size="icon-xs" aria-label={`Delete ${p.name}`} onClick={onDelete}>
            <Trash2Icon />
          </Button>
        </div>
      )}
    </li>
  );
}

export function ProvidersScreen() {
  const providers = useProviders();
  const remove = useDeleteProvider();
  const { canWrite } = usePermissions();
  const [dialog, setDialog] = React.useState<{ open: boolean; provider: Provider | null; stage: Stage }>({ open: false, provider: null, stage: "stt" });
  const [target, setTarget] = React.useState<Provider | null>(null);
  const list = providers.data ?? [];

  return (
    <>
      <PageHeader
        title="Providers"
        description="Where agents listen, think and speak. Mix self-hosted models with cloud APIs; switch an agent's provider without touching code."
        actions={
          canWrite && (
            <Button onClick={() => setDialog({ open: true, provider: null, stage: "stt" })}>
              <PlusIcon />
              Add provider
            </Button>
          )
        }
      />
      {providers.isPending ? (
        <Surface className="pt-3"><TableSkeleton rows={6} cols={3} /></Surface>
      ) : providers.isError && !providers.data ? (
        <Surface><ErrorState error={providers.error} onRetry={() => void providers.refetch()} /></Surface>
      ) : !list.length ? (
        <Surface>
          <EmptyState
            icon={CableIcon}
            title="No providers yet"
            description="An agent needs one speech-to-text, one language model and one text-to-speech provider. The bundled VoiceOS speech server gives you local Whisper and Kokoro with no API key."
            action={canWrite ? <Button size="sm" onClick={() => setDialog({ open: true, provider: null, stage: "stt" })}><PlusIcon />Add a provider</Button> : undefined}
          />
        </Surface>
      ) : (
        <div className="space-y-4">
          {STAGES.map((stage) => {
            const items = list.filter((p) => p.stage === stage);
            return (
              <Surface key={stage}>
                <SurfaceHeader
                  title={stageLabel(stage)}
                  titleExtra={<Hint term={stage === "stt" ? "stt" : stage === "llm" ? "llm" : "tts"} />}
                  action={
                    canWrite && (
                      <Button variant="subtle" size="xs" onClick={() => setDialog({ open: true, provider: null, stage })}>
                        <PlusIcon />
                        Add
                      </Button>
                    )
                  }
                />
                {items.length ? (
                  <ul className="divide-y divide-hairline pb-1">
                    {items.map((p) => (
                      <ProviderRow key={p.id} p={p} canWrite={canWrite} onEdit={() => setDialog({ open: true, provider: p, stage })} onDelete={() => setTarget(p)} />
                    ))}
                  </ul>
                ) : (
                  <p className="px-5 pb-5 text-[13px] text-muted-foreground">No {stageLabel(stage).toLowerCase()} provider yet: agents need one.</p>
                )}
              </Surface>
            );
          })}
        </div>
      )}
      <ProviderDialog open={dialog.open} onOpenChange={(o) => setDialog((d) => ({ ...d, open: o }))} provider={dialog.provider} stage={dialog.stage} />
      <ConfirmDialog
        open={!!target}
        onOpenChange={(o) => !o && setTarget(null)}
        title={`Delete ${target?.name ?? ""}?`}
        description="Agents that use it must switch to another provider first. Its sealed API key is deleted with it."
        confirmLabel="Delete provider"
        pending={remove.isPending}
        onConfirm={() =>
          target &&
          remove.mutate(target.id, {
            onSuccess: () => {
              toast.success(`${target.name} deleted.`);
              setTarget(null);
            },
            onError: (e) => toast.error(errorMessage(e)),
          })
        }
      />
    </>
  );
}
