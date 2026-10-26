"use client";

import { PipecatClient, type PipecatClientOptions } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import { WavMediaManager, WebSocketTransport } from "@pipecat-ai/websocket-transport";
import * as React from "react";

import { ApiError } from "@/lib/api/errors";
import type { SessionTicket } from "@/lib/api/types";

export type TransportChoice = "auto" | "webrtc" | "websocket";
export type Phase = "idle" | "connecting" | "listening" | "user" | "thinking" | "agent" | "ended" | "error";

export interface Line {
  id: number;
  who: "user" | "agent";
  text: string;
  final: boolean;
  interrupted?: boolean;
  /** For agent lines: caller stopped speaking to this answer's first audio, in the browser. */
  responseMs?: number;
}

export interface VoiceState {
  phase: Phase;
  transport: "webrtc" | "websocket" | null;
  lines: Line[];
  sessionId: string | null;
  error: string | null;
  micLevel: number;
  agentLevel: number;
}

const INITIAL: VoiceState = {
  phase: "idle",
  transport: null,
  lines: [],
  sessionId: null,
  error: null,
  micLevel: 0,
  agentLevel: 0,
};

const WEBRTC_TIMEOUT_MS = 8000;

/** Turn browser and runtime errors into what a person can act on. */
export function explain(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  const name = (err as { name?: string })?.name ?? "";
  const message = String((err as { message?: string })?.message ?? err ?? "");
  if (name === "NotAllowedError" || /permission/i.test(message))
    return "Microphone access was blocked. Allow the microphone for this site in the browser's address bar, then try again.";
  if (name === "NotFoundError") return "No microphone was found. Connect one and try again.";
  if (/busy|503/i.test(message)) return "Every voice slot is busy right now. Try again in a few seconds.";
  if (/timed out|timeout/i.test(message)) return "The voice connection timed out. Check that the runtime is reachable, then try again.";
  return message || "The voice connection failed. Try again.";
}

/**
 * One voice conversation with an agent through the Pipecat client.
 *
 * ``start`` asks for a ticket (via ``getTicket``, which calls the API), then connects over
 * WebRTC or WebSocket. With ``auto`` it tries WebRTC first and, if that does not connect in
 * time, takes a fresh ticket (tokens are single use) and falls back to WebSocket.
 */
export function useVoiceSession(getTicket: () => Promise<SessionTicket>) {
  const [state, setState] = React.useState<VoiceState>(INITIAL);
  const client = React.useRef<PipecatClient | null>(null);
  const audio = React.useRef<HTMLAudioElement | null>(null);
  const userStoppedAt = React.useRef<number | null>(null);
  const lineId = React.useRef(0);

  const patch = React.useCallback((p: Partial<VoiceState> | ((s: VoiceState) => Partial<VoiceState>)) => {
    setState((s) => ({ ...s, ...(typeof p === "function" ? p(s) : p) }));
  }, []);

  const upsert = React.useCallback((who: Line["who"], text: string, final: boolean, extra: Partial<Line> = {}) => {
    setState((s) => {
      const lines = [...s.lines];
      const last = lines[lines.length - 1];
      if (last && last.who === who && !last.final) {
        lines[lines.length - 1] = { ...last, text: who === "agent" ? `${last.text}${text}` : text, final, ...extra };
      } else if (text.trim()) {
        lines.push({ id: ++lineId.current, who, text, final, ...extra });
      }
      return { ...s, lines };
    });
  }, []);

  const callbacks = React.useMemo<PipecatClientOptions["callbacks"]>(
    () => ({
      onTrackStarted: (track, participant) => {
        // WebRTC: the agent's voice arrives as a remote track; play it.
        if (track.kind === "audio" && !participant?.local && audio.current) {
          audio.current.srcObject = new MediaStream([track]);
          void audio.current.play().catch(() => undefined);
        }
      },
      onBotReady: () => patch({ phase: "listening" }),
      onUserStartedSpeaking: () =>
        setState((s) => {
          const lines = [...s.lines];
          const last = lines[lines.length - 1];
          // Speaking over the agent interrupts it: mark its unfinished answer.
          if (s.phase === "agent" && last?.who === "agent") lines[lines.length - 1] = { ...last, interrupted: true, final: true };
          return { ...s, lines, phase: "user" };
        }),
      onUserStoppedSpeaking: () => {
        userStoppedAt.current = performance.now();
        patch({ phase: "thinking" });
      },
      onUserTranscript: (t) => upsert("user", t.text, Boolean(t.final)),
      onBotStartedSpeaking: () => {
        const started = userStoppedAt.current;
        userStoppedAt.current = null;
        const responseMs = started == null ? undefined : Math.round(performance.now() - started);
        setState((s) => {
          const lines = s.lines.map((l) => (l.who === "user" ? { ...l, final: true } : l));
          lines.push({ id: ++lineId.current, who: "agent", text: "", final: false, responseMs });
          return { ...s, lines, phase: "agent" };
        });
      },
      onBotOutput: (d) => {
        if (d.text) upsert("agent", d.text, false);
      },
      onBotStoppedSpeaking: () =>
        setState((s) => {
          const lines = [...s.lines];
          const last = lines[lines.length - 1];
          if (last?.who === "agent") lines[lines.length - 1] = { ...last, final: true };
          return { ...s, lines: lines.filter((l) => l.text.trim() || !l.final), phase: "listening" };
        }),
      onLocalAudioLevel: (level) => patch({ micLevel: level }),
      onRemoteAudioLevel: (level) => patch({ agentLevel: level }),
      onDisconnected: () => patch((s) => (s.phase === "error" ? {} : { phase: "ended", micLevel: 0, agentLevel: 0 })),
      onError: (msg) => patch({ phase: "error", error: explain(msg?.data ?? msg) }),
    }),
    [patch, upsert],
  );

  const connect = React.useCallback(
    async (kind: "webrtc" | "websocket") => {
      const ticket = await getTicket();
      patch({ sessionId: ticket.session_id, transport: kind });
      if (kind === "webrtc") {
        const ice = await fetch(ticket.ice_url).then((r) => (r.ok ? r.json() : { iceServers: [] }));
        const c = new PipecatClient({
          // All candidates go in the offer, so no follow-up PATCH has to find the same
          // runtime task behind a load balancer.
          transport: new SmallWebRTCTransport({
            iceServers: ice.iceServers ?? [],
            mediaManager: new WavMediaManager(),
            waitForICEGathering: true,
          }),
          enableMic: true,
          enableCam: false,
          callbacks,
        });
        client.current = c;
        await Promise.race([
          c.connect({ webrtcRequestParams: { endpoint: ticket.offer_url } }),
          new Promise((_, reject) => setTimeout(() => reject(new Error("WebRTC timed out")), WEBRTC_TIMEOUT_MS)),
        ]);
      } else {
        const c = new PipecatClient({
          transport: new WebSocketTransport({ mediaManager: new WavMediaManager() }),
          enableMic: true,
          enableCam: false,
          callbacks,
        });
        client.current = c;
        await c.connect({ wsUrl: ticket.websocket_url });
      }
    },
    [callbacks, getTicket, patch],
  );

  const start = React.useCallback(
    async (choice: TransportChoice) => {
      setState({ ...INITIAL, phase: "connecting" });
      lineId.current = 0;
      try {
        if (choice === "websocket") {
          await connect("websocket");
        } else {
          try {
            await connect("webrtc");
          } catch (err) {
            if (choice === "webrtc") throw err;
            await client.current?.disconnect().catch(() => undefined);
            await connect("websocket");
          }
        }
      } catch (err) {
        await client.current?.disconnect().catch(() => undefined);
        client.current = null;
        patch({ phase: "error", error: explain(err) });
      }
    },
    [connect, patch],
  );

  const stop = React.useCallback(async () => {
    await client.current?.disconnect().catch(() => undefined);
    client.current = null;
    patch({ phase: "ended", micLevel: 0, agentLevel: 0 });
  }, [patch]);

  React.useEffect(() => () => void client.current?.disconnect().catch(() => undefined), []);

  return { state, start, stop, audioRef: audio };
}
