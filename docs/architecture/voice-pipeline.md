# Voice pipeline

What happens inside the runtime during a call, how turns are taken, and how every number
on a session is measured. Code: `apps/api/src/voiceos/runtime/`.

<p align="center"><img src="../assets/diagrams/voice-turn.svg" alt="The stages of one turn" width="100%"></p>

## The pipeline

One Pipecat 1.14 pipeline per call, built from the agent by `pipeline.run_session()`:

```
transport.input ─► STT ─► user aggregator (Silero VAD + turn strategies) ─► TurnRouter
    ─► LLM (or LLMSwitcher: main / small) ─► TTS (phrase cache) ─► transport.output
    ─► assistant aggregator
```

| Stage | What runs | Notes |
| --- | --- | --- |
| Transport | `SmallWebRTCTransport` (aiortc) or `FastAPIWebsocketTransport` with Pipecat's protobuf serializer | Same pipeline either way |
| STT | The agent's STT provider (`providers.build_stt`): OpenAI-compatible (the VoiceOS speech server, any Whisper server), Deepgram, Sarvam | The language is the provider's, or the agent's |
| Turn taking | Silero VAD with the agent's pause (`vad_stop_secs`), then a turn strategy (below) | Waits up to `transcript_wait_s` for a slow transcript |
| Router | `TurnRouter` (`router.py`): response cache, small-model routing | Opt-in per agent |
| LLM | OpenAI-compatible (Ollama, vLLM, OpenAI, TokenShield, SmartRouter) or Anthropic, with the agent's tools | Every request bounded by the provider timeout |
| TTS | OpenAI-compatible (the VoiceOS speech server via `SpeechServerTTSService`), ElevenLabs, Cartesia, Sarvam, wrapped by the phrase cache | Any voice id the server accepts |

The greeting, when set, is spoken with a `TTSSpeakFrame` (no LLM call); without one the
LLM opens the conversation.

## Taking turns

- **Starting a turn.** Silero VAD and the transcript both start the caller's turn. With
  `interruption_min_words` above 1, a turn that starts while the agent is speaking needs
  that many words, which filters coughs and "uh huh".
- **Ending a turn.** `turn.mode = "smart"` (default) asks Pipecat's Smart Turn v3 model
  whether the caller has finished after each pause, so a mid-sentence pause does not end
  the turn. `turn.mode = "vad"` ends the turn after `vad_stop_secs` of silence.
- **Interruption.** With `allow_interruptions`, the caller speaking over the agent stops
  its audio at once and cancels the answer in flight; the interrupted turn is recorded as
  such, and its answer is never stored in the response cache.
- **Ending the call.** The client disconnecting (`client_left`), the `end_conversation`
  tool (`agent_ended`), `idle_timeout_s` without speech (`idle_timeout`),
  `max_duration_s` (`max_duration`), a runtime shutdown (`shutdown`) or an unhandled error
  (`error`).

## Measuring a turn

The `TurnRecorder` (`turns.py`) is a Pipecat observer. It sees every frame that moves
between processors and timestamps the ones that matter on the process's monotonic clock:

| Number | From | To |
| --- | --- | --- |
| `endpoint_ms` | the caller's last VAD stop (end of speech) | the turn being declared over |
| `stt_ms` | end of speech | the transcript (runs in parallel with turn detection) |
| `llm_first_token_ms` | the later of turn over and transcript in | the first LLM text |
| `tts_first_audio_ms` | the first LLM text | the first TTS audio frame |
| `response_ms` | end of speech | the agent starting to speak |

`response_ms` is the number a caller feels, including the wait while the turn detector
decides they are done. Nothing is estimated: a stage that did not run stays `None`.

A caller's turn opens on whichever user frame comes first (VAD start, the turn-start
frame, or the transcript), whenever the current turn is the greeting or is already being
answered. Pipecat's turn strategies can emit the turn-start frame after the transcript; an
earlier version opened turns only on that frame and attached the caller's words to the
greeting, with a meaningless response time on the next turn. The unit tests in
`tests/unit/runtime/test_turns.py` replay those frame orders.

The Talk page also shows the delay measured in the browser (end of the caller's speech to
the first agent audio received), which adds transport and buffering. The benchmark records
both.

## Usage

Usage comes from the services' own metrics frames: LLM prompt and completion tokens (and
whether the provider reported them), STT audio seconds, TTS characters. The phrase cache
counts the characters it replayed and the router counts response cache hits and turns
routed to the small model. See [latency-and-cost.md](latency-and-cost.md).

## When a provider fails

The runtime's `on_pipeline_error` handler:

- an **STT** failure: the caller hears "Sorry, I did not catch that. Could you say it
  again?",
- an **LLM** failure or timeout: "Sorry, I am having trouble answering right now. Please
  try again in a moment.",
- a **TTS** failure: nothing can be spoken; the error is recorded and the call continues.

Every error is recorded on its turn and on the session, and Pipecat sends the client an RTVI `error` message.

Two design notes from testing:

- The handler matches the failing processor **by identity**, not by name.
  `"OpenAISTTService"` contains the letters `TTS`, so a name check took every STT failure
  for a TTS failure and the caller heard nothing.
- Pipecat's `retry_on_timeout` re-issues a slow LLM request once **without** a timeout.
  `providers._bounded()` also bounds the provider SDK client by the provider's
  `timeout_s`, so the retry times out too and the caller hears the fallback instead of a
  hung turn. A single 5xx is retried by the provider SDK itself and usually succeeds.

TTS services get a stop timeout of the provider timeout clamped between 3 and 10 seconds,
so a slow but working synthesis is not cut off.

## The cost optimizer

- **Phrase cache** (`services/phrase_cache.py`): phrases of at most 200 characters are
  synthesized once per provider, model and voice, and replayed from memory with no
  provider call and no billed characters.
- **Response cache** (`router.py`, opt-in, agents without tools only): an exact repeat of a
  normalized question replays the stored answer with no LLM call. Keys include the agent
  version, so any edit retires old answers.
- **Small model routing**: with `llm_small_provider_id` set, turns of at most
  `small_model_max_words` words go to the small model through Pipecat's `LLMSwitcher`.

## Transports and NAT

WebRTC media is UDP. When the browser cannot reach the runtime directly (Docker, corporate
networks, the runtime in a private subnet), it relays through TURN: the browser's TURN URL
is `ICE_URLS`, and the runtime reaches the same coturn on its private address,
`SERVER_ICE_URLS`. Both sides get credentials minted per call. The browser gathers all
candidates before sending its offer, so signalling is one request. When WebRTC cannot
connect at all, the Talk page's "Auto" mode falls back to the WebSocket transport.
