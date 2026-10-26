/** Copy-ready code for the Integrations page and the key dialog. */

export function apiBase(origin: string): string {
  return origin.replace(/\/+$/, "");
}

export function startSessionSnippet(origin: string, key: string, agentId: string): string {
  return `# Your backend asks for a session ticket (one minute, one session)
curl -X POST ${apiBase(origin)}/v1/sessions \\
  -H "authorization: Bearer ${key}" \\
  -H "content-type: application/json" \\
  -d '{"agent_id": "${agentId}"}'
# => {"session_id": "...", "websocket_url": "...", "offer_url": "...", "ice_url": "...",
#     "disclosure": {"external": false, "providers": [], "message": "..."}}`;
}

export function browserSnippet(): string {
  return `import { PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";

// ticket = what your backend got from POST /v1/sessions (show ticket.disclosure.message first)
const { iceServers } = await (await fetch(ticket.ice_url)).json();
const client = new PipecatClient({
  transport: new SmallWebRTCTransport({ iceServers }),
  enableMic: true,
  enableCam: false,
  callbacks: {
    onUserTranscript: (t) => t.final && console.log("you:", t.text),
    onBotOutput: (d) => console.log("agent:", d.text),
  },
});
await client.connect({ webrtcRequestParams: { endpoint: ticket.offer_url } });`;
}

export function websocketSnippet(): string {
  return `import { PipecatClient } from "@pipecat-ai/client-js";
import { WebSocketTransport } from "@pipecat-ai/websocket-transport";

// No UDP path (strict firewall)? The same ticket works over a WebSocket.
const client = new PipecatClient({ transport: new WebSocketTransport(), enableMic: true, enableCam: false });
await client.connect({ wsUrl: ticket.websocket_url });`;
}

export function pythonSnippet(origin: string, key: string, agentId: string): string {
  return `import httpx

ticket = httpx.post(
    "${apiBase(origin)}/v1/sessions",
    headers={"authorization": "Bearer ${key}"},
    json={"agent_id": "${agentId}"},
).json()
print(ticket["disclosure"]["message"])  # tell the caller before connecting
print(ticket["websocket_url"])`;
}

export function openaiProviderSnippet(): string {
  return `# Any OpenAI-compatible server works as a provider, for example:
#   Ollama            http://ollama:11434/v1        (LLM, self-hosted)
#   vLLM              http://vllm:8000/v1           (LLM, self-hosted)
#   VoiceOS speech    http://speech:8080/v1         (Whisper STT, Kokoro TTS)
#   TokenShield       https://shield.example/v1     (LLM spend under a hard budget)
#   SmartRouter       https://router.example/v1     (model "auto": cheapest model that fits)`;
}
