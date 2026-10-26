# ADR-0001: Pipecat is the voice runtime

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

A real-time voice agent needs streaming audio transports (WebRTC and WebSocket), voice
activity detection, turn detection that tolerates mid-sentence pauses, interruption that
cancels work in flight, and adapters for many STT, LLM and TTS vendors. Each of those is
a project on its own, and getting them subtly wrong (echo, double answers, an agent that
talks over the caller) is what makes voice agents feel broken. VoiceOS's value is
elsewhere: self-hosting, provider choice per agent, honest measurement, privacy defaults.

## Decision

Build the runtime on Pipecat (BSD-2-Clause), pinned to 1.14.0: SmallWebRTC (aiortc) and
FastAPI WebSocket transports, Silero VAD, Smart Turn v3, `LLMContextAggregatorPair` with
user turn strategies, `LLMSwitcher`, and Pipecat's service classes per vendor. VoiceOS
adds, around it: the agent and provider model, session tokens and admission, the
`TurnRecorder` observer that measures every turn, the `TurnRouter` (response cache, small
model routing), the phrase cache, fallbacks on provider failure, and session reports.
The browser uses Pipecat's client with its local media manager.

## Consequences

**Good**
- Turn taking, interruption and transports are mature from day one, and new vendors come
  with Pipecat releases.
- The same client libraries work for the dashboard and for integrators' own apps.

**Bad / caveats**
- Pipecat moves fast; upgrades need the voice integration suite (`test_voice_*`), which
  drives the real pipeline, to stay green. The pin is exact for that reason.
- Some behaviour had to be worked around and is covered by tests: the turn-start frame can
  arrive after the transcript (the recorder opens turns on any user frame), segmented STT
  errors reach the error handler named in a way that contains "TTS" (matched by identity),
  `retry_on_timeout` retries without a timeout (the client is bounded too), and the
  default browser media manager loads Daily's remote bundle (the local one is used).

## Alternatives considered

- **LiveKit Agents**: excellent, but built around a LiveKit server (an SFU) as the media
  plane, which is more infrastructure than a self-hosted single-team deployment needs.
- **Writing the pipeline ourselves**: the turn-taking and interruption details are where
  most of the effort and most of the user-visible bugs are.
