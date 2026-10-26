"use client";

import { ArrowRightIcon, AudioLinesIcon, BotIcon, PlusIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Surface } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/features/auth/api";
import { errorMessage } from "@/lib/api/errors";
import type { Agent } from "@/lib/api/types";
import { languageLabel } from "@/lib/chips";
import { cn } from "@/lib/cn";
import { formatRelative } from "@/lib/format";

import { useAgents, useCreateFromTemplate, useTemplates } from "../api";

function NewAgentDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const templates = useTemplates();
  const create = useCreateFromTemplate();
  const router = useRouter();
  const [template, setTemplate] = React.useState("receptionist");
  const [name, setName] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setName("");
      setError(null);
    }
  }, [open]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      { template, name: name.trim() || null },
      {
        onSuccess: (agent) => {
          toast.success(`${agent.name} is ready. Say hello on the Talk page.`);
          onOpenChange(false);
          router.push(`/agents/${agent.id}`);
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>New agent</DialogTitle>
          <DialogDescription>
            Start from a template. It uses your self-hosted speech providers by default, so it works with no API key; change anything afterwards.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogBody className="space-y-4">
            {templates.isError ? (
              <ErrorState compact error={templates.error} onRetry={() => void templates.refetch()} />
            ) : (
              <div role="radiogroup" aria-label="Template" className="grid gap-2 sm:grid-cols-2">
                {(templates.data ?? []).map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    role="radio"
                    aria-checked={template === t.id}
                    onClick={() => setTemplate(t.id)}
                    className={cn(
                      "rounded-xl bg-muted px-3.5 py-3 text-left transition-[background-color,box-shadow] hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
                      template === t.id && "bg-primary-soft ring-2 ring-primary/40",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2 text-[13.5px] font-semibold">
                      {t.name}
                      <span className="text-[11px] font-normal text-muted-foreground">{languageLabel(t.language)}</span>
                    </div>
                    <div className="mt-0.5 text-[12px] leading-snug text-muted-foreground">{t.description}</div>
                  </button>
                ))}
                {templates.isPending && Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}
              </div>
            )}
            <Field label="Name" htmlFor="agent-name" hint="Empty: the template's name">
              <Input id="agent-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Clinic front desk" />
            </Field>
            {error && <FieldError>{error}</FieldError>}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending || !templates.data}>
              {create.isPending ? "Creating..." : "Create agent"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Stage({ label, name, external }: { label: string; name: string; external: boolean }) {
  return (
    <div className="min-w-0 flex-1 rounded-lg bg-muted/70 px-2.5 py-2">
      <div className="text-[10.5px] font-semibold tracking-wide text-faint uppercase">{label}</div>
      <div className="flex items-center gap-1 truncate text-[12.5px] font-medium">
        <span className="truncate">{name}</span>
        {external && <span className="size-1.5 shrink-0 rounded-full bg-warning" title="External provider" />}
      </div>
    </div>
  );
}

function AgentCard({ a }: { a: Agent }) {
  return (
    <Surface className="flex flex-col p-5" data-testid="agent-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/agents/${a.id}`} className="text-[15px] font-semibold hover:underline">
            {a.name}
          </Link>
          <p className="mt-0.5 line-clamp-2 text-[12.5px] text-muted-foreground">{a.description || a.greeting || "No description"}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <Chip tone="neutral">{languageLabel(a.language)}</Chip>
          {!a.enabled && <Chip tone="neutral">Disabled</Chip>}
        </div>
      </div>
      <div className="mt-4 flex items-stretch gap-1.5">
        <Stage label="Listens" name={a.stt.name} external={a.stt.external} />
        <ArrowRightIcon className="size-3.5 shrink-0 self-center text-faint" />
        <Stage label="Thinks" name={a.llm.name} external={a.llm.external} />
        <ArrowRightIcon className="size-3.5 shrink-0 self-center text-faint" />
        <Stage label="Speaks" name={a.tts.name} external={a.tts.external} />
      </div>
      <div className="mt-4 flex items-center justify-between gap-2">
        <span className="text-[11.5px] text-faint">
          {a.external_providers.length ? `Sends to ${a.external_providers.join(", ")}` : "Everything stays on your servers"} &middot; v{a.version}, {formatRelative(a.updated_at)}
        </span>
        <div className="flex gap-1">
          <Button variant="subtle" size="xs" nativeButton={false} render={<Link href={`/agents/${a.id}`} />} aria-label={`Edit ${a.name}`}>
            Edit
          </Button>
          <Button size="xs" nativeButton={false} render={<Link href={`/talk?agent=${a.id}`} />} disabled={!a.enabled} aria-label={`Talk to ${a.name}`}>
            <AudioLinesIcon />
            Talk
          </Button>
        </div>
      </div>
    </Surface>
  );
}

export function AgentsScreen() {
  const agents = useAgents();
  const { canWrite } = usePermissions();
  const params = useSearchParams();
  const [open, setOpen] = React.useState(false);
  React.useEffect(() => {
    if (params.get("new") === "1" && canWrite) setOpen(true);
  }, [params, canWrite]);

  return (
    <>
      <PageHeader
        title="Agents"
        description="Each agent pairs a prompt with providers for listening, thinking and speaking, plus how it takes turns, what it remembers and what it costs."
        actions={
          canWrite && (
            <Button onClick={() => setOpen(true)}>
              <PlusIcon />
              New agent
            </Button>
          )
        }
      />
      {agents.isPending ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-48 rounded-2xl" />)}
        </div>
      ) : agents.isError && !agents.data ? (
        <Surface><ErrorState error={agents.error} onRetry={() => void agents.refetch()} /></Surface>
      ) : !agents.data?.length ? (
        <Surface>
          <EmptyState
            icon={BotIcon}
            title="No agents yet"
            description="Pick a template (receptionist, support, tutor, meeting assistant or Hindi tutor) and talk to it in under a minute."
            action={canWrite ? <Button size="sm" onClick={() => setOpen(true)}><PlusIcon />Create your first agent</Button> : undefined}
          />
        </Surface>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {agents.data.map((a) => <AgentCard key={a.id} a={a} />)}
        </div>
      )}
      <NewAgentDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
