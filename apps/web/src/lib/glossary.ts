/** Plain-words explanations for VoiceOS's vocabulary, shown as inline hints. */
export const GLOSSARY = {
  responseTime:
    "From the moment the caller stops talking to the agent's first audio: what a caller feels. Measured per turn by the runtime, including the wait while the turn detector decides the caller is done.",
  endpoint:
    "End of turn: the time after the caller's last word before VoiceOS decides they have finished (a short silence, checked by the Smart Turn model so a mid-sentence pause does not count).",
  stt: "Speech to text: how long recognition took after the caller stopped speaking. It runs while the end of turn is being decided.",
  llm: "Time to the language model's first token once the turn is over and the transcript is in.",
  tts: "Speech synthesis: from the first token to the first audio the agent sends.",
  external:
    "An external provider runs outside your infrastructure: audio or transcripts are sent to it. Callers are told before a session starts. Self-hosted providers keep everything on your servers.",
  selfHosted:
    "Runs on your own infrastructure (local Whisper, Kokoro, Ollama or your own server). It has no per-call price; your hardware and power costs are not counted.",
  cost: "Estimated from each provider's list price and the usage it reported (audio seconds, tokens, characters). A stage that reports no usage or has no price shows as not reported, never as zero.",
  savings:
    "What the caches avoided at list price: repeated phrases replayed instead of synthesized, and repeated questions answered from the response cache.",
  interruption:
    "The caller spoke while the agent was talking. The agent stops at once and listens; its unfinished answer is cancelled.",
  retention:
    "How long transcripts are kept. 0 means words are never stored, only timings and usage. Personal details are redacted before anything is stored.",
  phraseCache: "Phrases the agent says often (greetings, confirmations) are synthesized once and replayed.",
  responseCache:
    "An exact repeat of a question replays the stored answer with no language model call. Only for agents without tools.",
  smallModel: "Short turns go to a smaller, cheaper model; everything else to the main model.",
  transport:
    "WebRTC carries audio over UDP with echo cancellation built into the browser; WebSocket carries it over a plain connection when WebRTC cannot connect.",
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
