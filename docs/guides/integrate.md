# Integrate VoiceOS into your app

Put a VoiceOS agent in your own website or app: your backend trades an SDK key for a
one-minute session ticket, and the browser connects to the runtime with it using any
Pipecat client. The Integrations page in the dashboard shows the same snippets with your
URL and an agent id filled in.

```
your backend ──POST /v1/sessions (SDK key)──► VoiceOS API ──► ticket
browser ──GET ice_url, then WebRTC offer_url or WebSocket websocket_url──► VoiceOS runtime
```

## 1. Create an SDK key

On **SDK keys**, create a key and copy it (it is shown once). Keys belong on your server,
never in the browser. Scope a key to the agents it may start and, if a browser page calls
`/v1/sessions` itself, to the website origins allowed to use it. Each key has a rate limit
(requests per minute) and an optional expiry.

## 2. Ask for a session ticket (your backend)

```bash
# Your backend asks for a session ticket (one minute, one session)
curl -X POST https://voice.example.com/v1/sessions \
  -H "authorization: Bearer vos_..." \
  -H "content-type: application/json" \
  -d '{"agent_id": "AGENT_ID"}'
# => {"session_id": "...", "websocket_url": "...", "offer_url": "...", "ice_url": "...",
#     "disclosure": {"external": false, "providers": [], "message": "..."}}
```

Or in Python:

```python
import httpx

ticket = httpx.post(
    "https://voice.example.com/v1/sessions",
    headers={"authorization": "Bearer vos_..."},
    json={"agent_id": "AGENT_ID"},
).json()
print(ticket["disclosure"]["message"])  # tell the caller before connecting
print(ticket["websocket_url"])
```

The ticket holds:

| Field | Meaning |
| --- | --- |
| `session_id` | The session's id; the finished session appears under this id in the dashboard and `GET /api/v1/sessions/{id}` |
| `token`, `expires_in_s` | The session token (60 s, single use); it is already in the URLs below |
| `websocket_url`, `offer_url`, `ice_url` | The runtime endpoints, with the token |
| `agent` | The agent's id, name and language |
| `disclosure` | `external`, `providers` and `message`: **show the message to the caller before connecting** |

Errors: 401 (bad or revoked key), 403 `agent_not_allowed` or `origin_not_allowed` (key
scope), 404 (agent missing or disabled), 429 (rate limit, with `Retry-After`).

## 3. Connect from the browser

Send the ticket to the page, show `disclosure.message`, then connect with the Pipecat
client (`@pipecat-ai/client-js` and a transport). WebRTC gives the lowest latency and the
browser's echo cancellation:

```javascript
import { PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport, WavMediaManager } from "@pipecat-ai/small-webrtc-transport";

// ticket = what your backend got from POST /v1/sessions (show ticket.disclosure.message first)
const { iceServers } = await (await fetch(ticket.ice_url)).json();
const client = new PipecatClient({
  // WavMediaManager keeps the microphone local (the default one loads code from a CDN);
  // waitForICEGathering sends every candidate in the offer, one request per call.
  transport: new SmallWebRTCTransport({ iceServers, mediaManager: new WavMediaManager(), waitForICEGathering: true }),
  enableMic: true,
  enableCam: false,
  callbacks: {
    onUserTranscript: (t) => t.final && console.log("you:", t.text),
    onBotOutput: (d) => console.log("agent:", d.text),
  },
});
await client.connect({ webrtcRequestParams: { endpoint: ticket.offer_url } });
```

When there is no UDP path (a strict firewall), the same kind of ticket works over a
WebSocket:

```javascript
import { PipecatClient } from "@pipecat-ai/client-js";
import { WavMediaManager, WebSocketTransport } from "@pipecat-ai/websocket-transport";

// No UDP path (strict firewall)? The same ticket works over a WebSocket.
const client = new PipecatClient({
  transport: new WebSocketTransport({ mediaManager: new WavMediaManager() }),
  enableMic: true,
  enableCam: false,
});
await client.connect({ wsUrl: ticket.websocket_url });
```

These are the snippets the dashboard's Integrations page shows. A ticket is single use:
to fall back from WebRTC to WebSocket, ask your backend for a new one.

### Keep third parties out of the browser

By default the Pipecat transports use a media manager that downloads Daily's call-machine
bundle from Daily's CDN (and reports errors to Sentry). That is why the snippets above, and
the VoiceOS dashboard, pass Pipecat's local `WavMediaManager`: the browser talks only to
your site and the runtime. It records and plays audio in AudioWorklets created from
`blob:` URLs, so a Content-Security-Policy on your page needs `script-src` and
`worker-src` to allow `blob:`, and `connect-src` to allow the runtime's origin
(`https://` and `wss://`).

### Origins

The runtime accepts browsers only from `ALLOWED_ORIGINS`; add your site's origin there.
With an origin-scoped key, `/v1/sessions` requires the request's `Origin` to be one of the
key's origins and binds the token to it, so the ticket only works from that site.

## 4. After the call

The runtime reports the session a moment after the call ends. A dashboard user (or a
`session_token` from `POST /api/v1/auth/login`, sent as a Bearer token) can read it at
`GET /api/v1/sessions/{session_id}`: turns
with words (if the agent's retention keeps them) and every stage's timing, usage, cost by
stage and the providers that received audio or text.

## Providers from the Euron stack

Every stage speaks the OpenAI API shape, so self-hosted servers and the rest of the Euron
AI stack plug in as providers:

```text
# Any OpenAI-compatible server works as a provider, for example:
#   Ollama            http://ollama:11434/v1        (LLM, self-hosted)
#   vLLM              http://vllm:8000/v1           (LLM, self-hosted)
#   VoiceOS speech    http://speech:8080/v1         (Whisper STT, Kokoro TTS)
#   TokenShield       https://shield.example/v1     (LLM spend under a hard budget)
#   SmartRouter       https://router.example/v1     (model "auto": cheapest model that fits)
```

- [TokenShield](https://github.com/euron-sde-team/euron-open-tokenshield): point an LLM
  provider at it to put every conversation's language model spend under a hard budget.
- [SmartRouter](https://github.com/euron-sde-team/euron-open-smart-router): use model
  `auto` to answer each turn with the cheapest model that fits.
