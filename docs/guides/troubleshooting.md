# Troubleshooting

## Local stack

| Symptom | Cause | Fix |
| --- | --- | --- |
| `make up` fails with "port is already allocated" | Another service owns one of 4510, 4530, 4535, 4537, 4542, 4550, 4566, 4578, 4579 or the relay range 4581 to 4589 | Set the matching `VOS_*_PORT` in `deploy/compose/.env` ([configuration.md](configuration.md#local-stack)), then `make up` again. The relay range is fixed in `compose.yaml` |
| Compose says "run `make env` first" | `deploy/compose/.env` is missing, or a required secret in it is empty. Running `docker compose` by hand skips `make env` | `make env` (it never overwrites an existing file). To regenerate, delete `deploy/compose/.env` first, then `make down` so the database matches the new demo password |
| The first `make up` takes long | Images build and the `models` one-shot downloads Whisper and Kokoro | Later starts reuse the image cache and the `voiceos-models` volume, which `make down` keeps (only `make clean` deletes it) |
| The `models` one-shot stalls or exits on a download | A model host is down or throttled. Each file is retried with backoff and resumed where it stopped; a host slower than 100 kB/s for 30 s is left for the next mirror (keeping what arrived), and if every mirror is slow the download continues at whatever speed it gets; every file is checked against a pinned SHA-256 | Run `make up` again (it resumes). To use your own copy, put `kokoro-v1.0.int8.onnx` and `voices-v1.0.bin` behind any HTTPS URL and set `VOS_KOKORO_MIRROR` to it; it is tried first and checked the same way |
| `make demo` fails with "Set VOS_DEMO_PASSWORD" | The seed reads the demo password from the environment | Run it through `make demo`, which passes the stack's `.env` |
| Integration tests refuse to run | The database name lacks `test`, or the host is not local. The suite drops and recreates it | Point `TEST_DATABASE_URL` at a `*_test` database; `ALLOW_REMOTE_TEST_DB=true` only for a disposable CI host |
| Python tests fail with `ModuleNotFoundError: pipecat` | The runtime extra is not installed | `cd apps/api && uv sync --extra runtime` |
| The API refuses to boot: "unsafe production configuration: ..." | `ENVIRONMENT=production` with a development or short secret, equal secrets, `COOKIE_SECURE=false` or an endpoint override on `aws` | Fix each item the message lists ([configuration.md](configuration.md#production-boot-guards)) |

## Talking to an agent

| Symptom | Cause | Fix |
| --- | --- | --- |
| "Microphone access was blocked" | The browser denied the microphone for this site | Allow it in the address bar's site settings, then **Talk again**. The dashboard must be served from `localhost` or HTTPS: browsers only give the microphone to secure origins |
| "The voice connection timed out" on WebRTC | WebRTC media cannot reach the runtime. In Docker the runtime's container address is not reachable from the browser, so media must go through TURN | Check `ICE_URLS` (what browsers use, `turn:127.0.0.1:4578?transport=udp` locally) and `SERVER_ICE_URLS` (what the runtime uses, `turn:turn:3478?transport=udp` locally): if the runtime is given the browser's address, it points at itself inside its container and relay gathering stalls. Check `TURN_PASSWORD` equals coturn's secret. Or pick **WebSocket** |
| Connected, but the agent never answers, and the speech service logs `failed to map segment from shared object` | Kokoro's phonemizer copies `libespeak-ng` into `/tmp` and loads it; a `noexec` tmpfs refuses | Mount the speech container's `/tmp` with `exec` (`compose.yaml` does: `/tmp:exec,uid=10001,gid=10001`) |
| The Talk page stays on "Connecting..." and the browser console reports a Content Security Policy violation | The dashboard's CSP allows only the runtime origin named by `RUNTIME_PUBLIC_URL`, and the ticket points elsewhere | Set the web service's `RUNTIME_PUBLIC_URL` to the same value as the API's |
| "Every voice slot is busy right now" (503 `runtime_busy`) | The runtime instance holds `MAX_SESSIONS` calls | Wait, raise `MAX_SESSIONS` (if the CPU allows), or run more runtime instances |
| The connection is refused with 403 | The page's origin is not in the runtime's `ALLOWED_ORIGINS`, or differs from the origin the ticket was issued for | Add the origin to `ALLOWED_ORIGINS`; request the ticket from the page that connects |
| The connection is refused with 409 `token_used` | A ticket is single use | Ask for a new ticket per connection attempt (the Talk page does when it falls back) |
| Answers take several seconds, and `stt_ms` or `endpoint_ms` dominates the waterfall | Local Whisper on a busy or small CPU. The turn waits for the transcript, so slow recognition shows as a long end of turn | Use a smaller Whisper (`whisper-tiny` or `whisper-base`), give the speech container more CPUs, keep `SPEECH_THREADS` x `SPEECH_CONCURRENCY` within its cores, stop other heavy work on the machine, or use a GPU (`WHISPER_DEVICE=cuda`) or a hosted STT |
| A turn has your words but "No words in this turn" follows, or the agent ignores what you said | The transcript arrived after `transcript_wait_s` and the turn was treated as empty | Raise the agent's **Transcript wait** (`turn.transcript_wait_s`, up to 30 s) or speed up recognition as above |
| The agent talks over itself or answers its own voice | Speakers feeding the microphone | Use headphones; WebRTC enables the browser's echo cancellation |
| "Sorry, I did not catch that" | The STT provider failed or timed out | Check the provider with **Test** on the Providers page; the error is on the session |
| "Sorry, I am having trouble answering right now" | The LLM provider failed or exceeded its timeout (each request, including Pipecat's retry, is bounded by the provider's `timeout_s`) | Check the provider; raise its timeout if the model is slow to start |
| Hindi answers are recognized as gibberish | Whisper `base` handles Hindi poorly | Use `whisper-small` (the Hindi tutor template's provider in the demo) or Sarvam |

## Numbers

| Symptom | Cause | Fix |
| --- | --- | --- |
| Cost shows "not reported" | The provider has no price configured, or it did not report usage | Enter the provider's list prices on the Providers page. VoiceOS ships no price list |
| Cost shows "Self-hosted" | Every stage runs on your infrastructure | Expected: no per-call price; hardware is not modelled |
| An agent edit does not apply to the next call | Each call loads its agent fresh with its ticket claim, but the control plane caches resolved agents for 5 s; without Redis, another API replica only drops its copy when that expires | Wait a few seconds, or set `REDIS_URL` so every replica invalidates at once; calls in progress keep their version |
| An agent cannot take calls (404 "agent not found or disabled") although it is enabled | One of its STT, LLM or TTS providers is disabled; a disabled provider receives nothing | Enable the provider, or switch the agent to another one (a disabled small model only turns routing off) |
| The overview lags a finished call by a few seconds | The runtime reports the session when the call ends, then the overview is cached for 15 s | Expected |
