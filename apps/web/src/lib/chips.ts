/**
 * One mapping from states to a chip tone, label and explanation, so a status reads the
 * same on every screen.
 */

export type Tone = "success" | "savings" | "info" | "primary" | "warning" | "danger" | "neutral";

export interface ChipSpec {
  label: string;
  tone: Tone;
  hint: string;
}

const END: Record<string, ChipSpec> = {
  client_left: { label: "Caller hung up", tone: "neutral", hint: "The caller closed the connection." },
  agent_ended: { label: "Agent ended", tone: "success", hint: "The agent said goodbye and ended the call." },
  idle_timeout: { label: "Idle", tone: "warning", hint: "Nobody spoke for the agent's idle timeout." },
  max_duration: { label: "Time limit", tone: "warning", hint: "The session reached the agent's maximum length." },
  error: { label: "Error", tone: "danger", hint: "The session failed; see its errors." },
  shutdown: { label: "Shutdown", tone: "neutral", hint: "The runtime restarted during the session." },
  rejected: { label: "Rejected", tone: "danger", hint: "The runtime refused the session." },
};

const COST: Record<string, ChipSpec> = {
  complete: { label: "Estimated", tone: "primary", hint: "Every stage reported usage and has a price." },
  partial: { label: "Partial", tone: "warning", hint: "Some stages reported no usage or have no price." },
  not_reported: { label: "Not reported", tone: "neutral", hint: "No stage reported usage with a price." },
  self_hosted: { label: "Self-hosted", tone: "savings", hint: "Every stage runs on your servers: no per-call price. Hardware costs are not counted." },
};

const JOB: Record<string, ChipSpec> = {
  queued: { label: "Queued", tone: "neutral", hint: "Waiting for the worker to pick it up." },
  running: { label: "Running", tone: "info", hint: "The worker is holding conversations with the agents now." },
  succeeded: { label: "Done", tone: "success", hint: "Every conversation ran and its timings were collected." },
  failed: { label: "Failed", tone: "danger", hint: "The run stopped; its error says why." },
};

const ADAPTER: Record<string, string> = {
  openai_compatible: "OpenAI-compatible",
  deepgram: "Deepgram",
  sarvam: "Sarvam",
  anthropic: "Anthropic",
  elevenlabs: "ElevenLabs",
  cartesia: "Cartesia",
  mock: "Mock (tests and demo)",
};

const STAGE: Record<string, string> = { stt: "Speech to text", llm: "Language model", tts: "Text to speech" };

const LANGUAGE: Record<string, string> = { en: "English", hi: "Hindi", mr: "Marathi" };

const fallback = (value: string): ChipSpec => ({ label: value, tone: "neutral", hint: value });

export const endReason = (v: string): ChipSpec => END[v] ?? fallback(v);
export const costStatus = (v: string): ChipSpec => COST[v] ?? fallback(v);
export const jobChip = (v: string): ChipSpec => JOB[v] ?? fallback(v);
export const adapterLabel = (v: string): string => ADAPTER[v] ?? v;
export const stageLabel = (v: string): string => STAGE[v] ?? v;
export const languageLabel = (v: string): string => LANGUAGE[v.split("-")[0] ?? v] ?? v;
export const ADAPTERS_BY_STAGE: Record<string, string[]> = {
  stt: ["openai_compatible", "deepgram", "sarvam", "mock"],
  llm: ["openai_compatible", "anthropic", "mock"],
  tts: ["openai_compatible", "elevenlabs", "cartesia", "sarvam", "mock"],
};
