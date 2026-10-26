"use client";

import { CheckCircle2Icon, TriangleAlertIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { CodeBlock } from "@/components/code-block";
import { CopyButton } from "@/components/copy-button";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { useAgents } from "@/features/agents/api";
import { errorMessage } from "@/lib/api/errors";
import type { ApiKey, ApiKeyCreated } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { startSessionSnippet } from "@/lib/snippets";

import { useCreateKey, useUpdateKey } from "../api";

export function KeyRevealed({ created }: { created: ApiKeyCreated }) {
  const [origin, setOrigin] = React.useState("");
  React.useEffect(() => setOrigin(window.location.origin), []);
  return (
    <div className="space-y-4">
      <div className="flex gap-3 rounded-xl bg-warning-soft px-4 py-3 text-[13px]">
        <TriangleAlertIcon className="mt-0.5 size-4 shrink-0 text-warning" />
        <p className="text-foreground">
          Copy this key now. It is shown <strong>once</strong>; VoiceOS stores only a peppered hash and cannot show it again.
        </p>
      </div>
      <div className="flex items-center gap-2 rounded-xl bg-muted p-1.5 pl-3.5">
        <code className="min-w-0 flex-1 truncate font-mono text-[12.5px] select-all" data-testid="new-key">
          {created.key}
        </code>
        <CopyButton value={created.key} label="Copy key" variant="default" />
      </div>
      <CodeBlock samples={[{ id: "curl", label: "Start a session", code: startSessionSnippet(origin, created.key, created.agent_ids[0] ?? "AGENT_ID") }]} />
    </div>
  );
}

const ORIGIN = /^https?:\/\/[A-Za-z0-9.-]+(:[0-9]{1,5})?$/;

/** One origin per line or comma; trailing slashes dropped. Returns the list and any invalid entries. */
export function parseOrigins(value: string): { origins: string[]; invalid: string[] } {
  const items = value
    .split(/[\s,]+/)
    .map((o) => o.trim().replace(/\/+$/, ""))
    .filter(Boolean);
  return { origins: [...new Set(items)], invalid: items.filter((o) => !ORIGIN.test(o)) };
}

/** "2026-12-31" -> the end of that day in UTC, so a key works through its last day. */
export function expiryFromDate(value: string): string | null {
  if (!value) return null;
  const d = new Date(`${value}T23:59:59Z`);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/** Creates a key, or edits one when `editing` is set (the secret is never shown again). */
export function CreateKeyDialog({
  open,
  onOpenChange,
  editing = null,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  editing?: ApiKey | null;
}) {
  const create = useCreateKey();
  const update = useUpdateKey();
  const pending = create.isPending || update.isPending;
  const agents = useAgents();
  const [name, setName] = React.useState("");
  const [rpm, setRpm] = React.useState("");
  const [agentIds, setAgentIds] = React.useState<string[]>([]);
  const [origins, setOrigins] = React.useState("");
  const [expires, setExpires] = React.useState("");
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [created, setCreated] = React.useState<ApiKeyCreated | null>(null);

  React.useEffect(() => {
    if (open) {
      setName(editing?.name ?? "");
      setRpm(editing?.rpm_limit ? String(editing.rpm_limit) : "");
      setAgentIds(editing?.agent_ids ?? []);
      setOrigins((editing?.allowed_origins ?? []).join("\n"));
      setExpires(editing?.expires_at ? editing.expires_at.slice(0, 10) : "");
      setErrors({});
      setServerError(null);
      setCreated(null);
    }
  }, [open, editing]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!name.trim()) errs.name = 'Name it after the app that uses it, for example "support-bot".';
    const n = rpm.trim() ? Number(rpm) : null;
    if (n != null && (!Number.isInteger(n) || n < 1)) errs.rpm = "Whole number above 0, or empty for the service default.";
    const expiresAt = expiryFromDate(expires);
    if (expires && (!expiresAt || new Date(expiresAt) <= new Date())) errs.expires = "Pick a date from today on, or leave it empty for no expiry.";
    const parsed = parseOrigins(origins);
    if (parsed.invalid.length) errs.origins = `Not an origin: ${parsed.invalid[0]}. Use scheme and host only, like https://app.example.com`;
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setServerError(null);
    const body = {
      name: name.trim(),
      rpm_limit: n,
      agent_ids: agentIds,
      allowed_origins: parsed.origins,
      expires_at: expiresAt,
    };
    if (editing) {
      update.mutate(
        { id: editing.id, body },
        {
          onSuccess: () => {
            toast.success(`Key "${body.name}" updated.`);
            onOpenChange(false);
          },
          onError: (err) => setServerError(errorMessage(err)),
        },
      );
      return;
    }
    create.mutate(body, {
      onSuccess: (k) => {
        setCreated(k);
        toast.success("SDK key created.");
      },
      onError: (err) => setServerError(errorMessage(err)),
    });
  }

  const toggleAgent = (id: string) => setAgentIds((a) => (a.includes(id) ? a.filter((x) => x !== id) : [...a, id]));

  return (
    <Dialog open={open} onOpenChange={(o) => !pending && onOpenChange(o)}>
      <DialogContent className={created ? "max-w-2xl" : "max-w-lg"}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {created && <CheckCircle2Icon className="size-5 text-savings" />}
            {created ? `Key "${created.name}" is ready` : editing ? `Edit "${editing.name}"` : "New SDK key"}
          </DialogTitle>
          <DialogDescription>
            {created
              ? "Keep it on your server and use it as a Bearer token to start sessions. Revoke it any time from SDK keys."
              : editing
                ? "Changes apply to the next session started with this key. The key itself stays the same."
                : "Your backend uses this key to start voice sessions with POST /v1/sessions."}
          </DialogDescription>
        </DialogHeader>
        {created ? (
          <>
            <DialogBody>
              <KeyRevealed created={created} />
            </DialogBody>
            <DialogFooter>
              <Button onClick={() => onOpenChange(false)}>I have copied the key</Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
            <DialogBody className="space-y-4">
              <Field label="Name" htmlFor="key-name" error={errors.name}>
                <Input id="key-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="support-bot" />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Requests per minute" htmlFor="key-rpm" error={errors.rpm} hint="Over it, calls get 429">
                  <Input id="key-rpm" inputMode="numeric" className="tabular" placeholder="Service default" value={rpm} onChange={(e) => setRpm(e.target.value)} />
                </Field>
                <Field label="Expires" htmlFor="key-expires" error={errors.expires} hint="Empty: never">
                  <Input id="key-expires" type="date" className="tabular" value={expires} onChange={(e) => setExpires(e.target.value)} />
                </Field>
              </div>
              <Field label="Agents" hint={agentIds.length ? `${agentIds.length} selected` : "None selected: every agent"}>
                {agents.isError ? (
                  <p className="text-[12.5px] text-muted-foreground">
                    Could not load the agents.{" "}
                    <button type="button" className="font-medium text-primary underline-offset-4 hover:underline" onClick={() => void agents.refetch()}>
                      Retry
                    </button>
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {(agents.data ?? []).map((a) => {
                      const on = agentIds.includes(a.id);
                      return (
                        <button
                          key={a.id}
                          type="button"
                          aria-pressed={on}
                          onClick={() => toggleAgent(a.id)}
                          className={cn(
                            "rounded-full bg-muted px-3 py-1 text-[12.5px] font-medium transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
                            on && "bg-primary-soft text-primary",
                          )}
                        >
                          {a.name}
                        </button>
                      );
                    })}
                  </div>
                )}
              </Field>
              <Field label="Allowed website origins" htmlFor="key-origins" error={errors.origins} hint="One per line. Empty: any origin">
                <Textarea id="key-origins" rows={2} className="font-mono text-[12.5px]" value={origins} onChange={(e) => setOrigins(e.target.value)} placeholder="https://app.example.com" />
              </Field>
              {serverError && <FieldError>{serverError}</FieldError>}
            </DialogBody>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={pending}>
                {editing ? (pending ? "Saving..." : "Save changes") : pending ? "Creating..." : "Create key"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
