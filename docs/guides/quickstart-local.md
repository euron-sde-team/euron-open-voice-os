# Quickstart (local)

Run the whole system on a laptop with only Docker: Postgres, Redis, the AWS emulator
(provisioned by the same Terraform as production), the local speech server (Whisper and
Kokoro), deterministic mock providers, the control plane, the voice runtime, a worker, a
TURN relay and the dashboard. No AWS account and no provider keys are needed.

## Prerequisites

- Docker with Compose v2 (Docker Desktop or Docker Engine), with at least 4 CPUs and 8 GB
  of memory available to it: local speech recognition is CPU bound
- `make`, `bash`, `openssl`, `curl` (and `jq` for the examples below)
- A browser with a microphone (Chrome, Edge, Firefox or Safari)
- For running tests outside containers: Python 3.12 with [uv](https://docs.astral.sh/uv/),
  Node 22 and pnpm

## Start

```bash
git clone https://github.com/euron-sde-team/euron-open-voice-os.git
cd euron-open-voice-os
make up      # writes deploy/compose/.env, builds images, downloads models, applies Terraform on Floci, migrates, starts everything
make demo    # users, providers, five agents, SDK keys, real conversations, a month of history, a benchmark
```

`make up` runs `make env` first, which writes `deploy/compose/.env` with random local-only
secrets (it never overwrites an existing file). The first start takes several minutes:
images build, the one-shot `models` container downloads Whisper tiny, base and small and
Kokoro into the `models` volume, and the `terraform` one-shot creates the objects bucket,
the KMS key and the secrets inside Floci. Later starts reuse both volumes.

`make demo` runs `voiceos seed-demo` in a worker container. It creates the demo users and
providers, an agent from every template, three SDK keys, then **holds real conversations**
with the agents through the runtime (the committed Kokoro utterances spoken into a
headless client), replays those recordings into a month of history, and runs a latency
benchmark. It ends with the sign-in:

```text
Sign in at the dashboard with any of:
  admin@voiceos.local
  riya.sharma@voiceos.local
  daniel.okafor@voiceos.local
Password: the VOS_DEMO_PASSWORD in deploy/compose/.env
```

`admin@voiceos.local` is the owner, Riya an admin, Daniel a viewer. The demo's language
model is the local mock provider (scripted answers that report token usage); one copy of
it is marked external and priced, to show disclosure and costing. Running `make demo`
again keeps the configuration and adds more conversations.

| Service | URL |
| --- | --- |
| Dashboard | http://localhost:4510 |
| Control plane API (and `POST /v1/sessions`) | http://localhost:4530 |
| API docs (Swagger) | http://localhost:4530/docs |
| Voice runtime (WebRTC offer, WebSocket) | http://localhost:4535 |
| Speech server (Whisper, Kokoro) | http://localhost:4537 |
| Mock providers (`/stats`, fault injection) | http://localhost:4550 |
| TURN (coturn) | localhost:4578 (UDP and TCP), relay ports 4581 to 4589 (UDP) |
| Postgres | localhost:4542 |
| Redis | localhost:4579 |
| Floci (AWS emulator) | http://localhost:4566 |

Every port binds to `127.0.0.1` and is overridable in `deploy/compose/.env` (the
`VOS_*_PORT` variables in [configuration.md](configuration.md#local-stack)).

## Talk to an agent

Open http://localhost:4510, sign in, and open **Talk**. Pick **Front desk**, press
**Start talking** and allow the microphone. Say "I would like to book a table for two
tonight". Use headphones, or the agent may hear itself.

The transcript shows your words and the agent's answer with the time it took. End the
conversation and follow **open this session**: the session shows each turn's waterfall
(end of turn, speech to text, first LLM token, first TTS audio), the cost by stage, and
which providers were used.

The connection picker defaults to **Auto** (WebRTC through the local TURN relay, then
WebSocket if WebRTC does not connect within 8 seconds).

## Make your own agent

**Agents** -> **New agent** -> pick a template -> **Create agent**. The template picks the
self-hosted providers, so it works at once. In the editor, switch any stage to another
provider, change the greeting, the instructions, the turn settings or the privacy settings,
and **Save**: the agent's version goes up and the next call uses it.

To use a real language model, add a provider on **Providers**: for example an
OpenAI-compatible LLM with your own Ollama and model `llama3.2` (from the containers, the
host is `http://host.docker.internal:11434/v1` on Docker Desktop; on Linux use the host's
address on the Docker bridge), or a hosted API with its key. Then select it on the agent.

## Start a session from your own backend

Create a key on **SDK keys** (scope it to an agent), then:

```bash
export VOS_KEY=vos_...        # shown once when you create it
export AGENT=...              # the agent's id, from its URL on the Agents page
curl -s http://localhost:4530/v1/sessions \
  -H "authorization: Bearer $VOS_KEY" \
  -H "content-type: application/json" \
  -d "{\"agent_id\": \"$AGENT\"}" | jq '{websocket_url, offer_url, ice_url, disclosure}'
```

The ticket is valid for one minute and one session. Connect a Pipecat client with it; see
[integrate.md](integrate.md).

## Stop

```bash
make down    # stops the stack and deletes its data (downloaded models are kept)
make clean   # also deletes the downloaded models (about 1 GB)
```

## Next

- [walkthrough.md](walkthrough.md): every screen.
- [configuration.md](configuration.md): every setting.
- [testing.md](testing.md): the test suites.
- [troubleshooting.md](troubleshooting.md): microphone, WebRTC, slow speech.
