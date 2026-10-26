# Walkthrough

Every screen of the dashboard, in the order you would use them. Run `make up && make demo`
and sign in at http://localhost:4510 as `admin@voiceos.local` (the password is
`VOS_DEMO_PASSWORD` in `deploy/compose/.env`) to follow along.

The sidebar has three groups: **Voice** (Talk, Agents, Providers), **Monitor** (Overview,
Sessions, Benchmarks) and **Connect** (SDK keys, Integrations), plus **Organisation**
(Users and the Audit log for admins) and Settings. Words like "end of turn", "external"
or "self-hosted" have an info hint next to them that explains them in plain words.

## Talk

Have a real conversation with an agent in the browser.

- **Agent**: pick who you talk to. Below it: the **Connection** (Auto, WebRTC or
  WebSocket), the **disclosure** (green when audio and transcripts stay on this deployment,
  amber naming every external provider otherwise), the providers it listens, thinks and
  speaks with, and chips for interruptions, turn detection and transcript retention.
- **Start talking** asks for the microphone and connects. The orb shows who is speaking;
  the transcript shows your words and the agent's, each answer with the time it took as
  this browser measured it, and "interrupted" when you spoke over it.
- **End conversation**, then **open this session** for the stored timings and cost.

## Agents

One card per agent: its three stages (Listens, Thinks, Speaks, with an amber dot on an
external provider), language, version and where its data goes. **New agent** creates one
from a template (Receptionist, Support agent, Tutor, Meeting assistant, Hindi tutor); the
template picks self-hosted providers, so it works without a key.

The editor:

- **Pipeline**: the STT, LLM and TTS providers, the voice, the language, and an optional
  small model for short turns.
- **What it says**: name, greeting (spoken first; empty lets the model open), instructions
  (the system prompt), description.
- **Conversation**: end of turn (Smart turn or Silence only), the pause, whether the
  caller can interrupt and after how many words, how long to wait for a slow transcript,
  the longest call, hang up after silence.
- **Privacy and cost**: transcript retention in days (0 keeps no words), redaction of
  personal details, the phrase cache, the response cache, the small-model word limit.
- **Tools and knowledge**: current time, FAQ lookup, end conversation, a webhook with its
  URL, and the FAQ itself.
- **Save** bumps the version; the next call uses it. Enabled and **Delete agent** at the
  bottom.

## Providers

Grouped by stage (speech to text, language model, text to speech). Each row shows the
adapter, model or voice, whether it is external or self-hosted, its price and how many
agents use it. **Add provider** takes the stage, adapter, name, base URL, model, voice,
language, API key (stored sealed, never shown again), prices, timeout, and "Treat as
external" for a private server outside your trust boundary. **Test** sends a small request
and reports the result and latency; a provider used by an agent cannot be deleted.

## Overview

The period (24 h, 7 d, 30 d) at the top. Tiles: median response time (with p95), sessions,
minutes talked, estimated cost, saved by caches, interruption rate, sessions that used
external providers and sessions with errors; response time, sessions, minutes and cost are compared with the previous period. Below: a chart
of sessions and average response time, **Where the time goes** (average end of turn, speech
to text, first LLM token, first TTS audio), and **By agent** (response time and cost per
session).

## Sessions

Every finished call, newest first, filterable by agent and to sessions with errors. A row
opens the session: how it ended, transport, whether audio or text left your servers;
duration, median response, interruptions, cost, savings, LLM tokens; **Cost by stage**
(an amount, "not reported" or "Self-hosted"); then each turn with the caller's and the
agent's words and its waterfall (end of turn, LLM first token, TTS first audio, and speech
to text in parallel underneath). Admins can **Erase transcript**: the words go, the
timings stay.

## Benchmarks

**Run benchmark** picks up to five agents and the number of conversations each. The worker
calls each agent like a real caller with recorded questions in its language, then the page
shows per agent the median and p95 response, what the benchmark client heard, the average
per stage and the providers, with the machine it ran on. History lists earlier runs.

## SDK keys

**New key**: name, the agents it may start (none selected means every agent), allowed
website origins, requests per minute and an expiry. The key is shown once, with a ready
`curl` to start a session. Keys can be edited and revoked.

## Integrations

The three steps to put an agent in your own app (key, ticket, browser connection) with
copy-ready snippets for curl, Python, WebRTC and WebSocket, and how self-hosted servers and
TokenShield or SmartRouter plug in as providers. See [integrate.md](integrate.md).

## Users, Audit log, Settings

- **Users** (owners manage, admins read): add users with a role (owner, admin, viewer),
  change roles, rename, disable.
- **Audit log** (admins): every change with who, what, when and from where, filterable by
  action (for example `agent.updated`).
- **Settings**: the deployment as the API sees it (version, environment, key sealing,
  storage, cache backend, the voice runtime's state and capacity, providers per stage),
  your account, the theme (light, dark, system) and your password.
