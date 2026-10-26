# ADR-0003: Local speech in its own service

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

"No cloud account needed" means VoiceOS must hear and speak locally. faster-whisper (MIT)
and Kokoro (MIT code, Apache-2.0 weights, with Hindi voices) fit, but they are CPU heavy,
need hundreds of megabytes of model files, and Kokoro's phonemizer depends on espeak-ng
and the phonemizer package, both GPL-3.0-or-later. Running them inside the runtime would
make every runtime instance carry the models and the GPL components, and would let a slow
synthesis starve the event loop of every call on that instance.

## Decision

Serve local speech from a separate `speech` service (`voiceos speech`, its own image with
the `speech` extra and the Debian espeak-ng package) behind OpenAI-compatible endpoints:
`POST /v1/audio/transcriptions` and streamed `POST /v1/audio/speech`, plus `/v1/voices` and
`/v1/models`. The runtime treats it like any other OpenAI-compatible provider. Models are
downloaded once into a volume by `voiceos models` (Kokoro files checked against pinned
SHA-256), and model calls are bounded by `SPEECH_CONCURRENCY` and `SPEECH_THREADS`.

## Consequences

**Good**
- The same agent switches between local and hosted speech by changing a provider, with no
  code path that knows the difference.
- Speech can scale, move to a GPU, or be left out entirely, independently of the runtime.
- The GPL components stay in one image; the control plane, runtime, worker and web images
  contain none of them ([licenses.md](../licenses.md)).

**Bad / caveats**
- One more network hop per STT and TTS request (on the private network).
- The speech image needs a writable, executable `/tmp`: phonemizer copies libespeak-ng
  there and loads it, which a default `noexec` tmpfs refuses.

## Alternatives considered

- **Whisper and Kokoro inside the runtime**: no hop, but heavier, GPL-carrying runtime
  images and no independent scaling.
- **Piper for TTS**: the `piper-tts` package is GPL-3.0 itself.
