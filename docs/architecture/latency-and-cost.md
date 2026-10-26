# Latency and cost

Two numbers per conversation that VoiceOS promises never to invent: how long the caller
waited for each answer, and what the conversation cost.

## Latency

Per turn, the runtime measures five values from the frames that flowed (see
[voice-pipeline.md](voice-pipeline.md#measuring-a-turn)): `endpoint_ms`, `stt_ms`,
`llm_first_token_ms`, `tts_first_audio_ms` and `response_ms`, all from the end of the
caller's speech as Silero VAD detected it. A stage that did not run is `None`.

Where they show up:

| Place | What |
| --- | --- |
| A session (dashboard drawer, `GET /api/v1/sessions/{id}`) | Every turn's values as a waterfall; the session's median and maximum `response_ms` |
| The overview (`GET /api/v1/analytics/overview`) | The period's `response_ms` p50 and p95 computed with `percentile_cont` over the turns themselves (not an average of averages), the average per stage, and an hourly or daily series |
| The runtime's `/metrics` | `voiceos_runtime_response_seconds`, a histogram per turn |
| A benchmark run | p50 and p95 of `response_ms`, stage averages, and the delay the benchmark client itself measured (end of its audio to the first reply audio), with the machine's CPU, core count and GPU |

Speech recognition and synthesis on CPU dominate the numbers on modest hardware, and
another workload on the same machine slows them further. Compare runs on the same quiet
machine; the benchmark result names the machine it ran on.

## Cost

### Units

All money is integer **nano-USD** (1 USD = 10^9 nUSD) in `BIGINT` columns, computed with
`Decimal` and rounded up (`core/money.py`), so a cost estimate never undercounts and sums
never drift. The API converts to USD only for display.

### Per stage

| Stage | Usage (reported by the provider) | Price (configured on the provider) | Cost |
| --- | --- | --- | --- |
| STT | audio seconds | `per_audio_minute` | seconds / 60 x price |
| LLM | prompt and completion tokens, and whether the provider reported them | `per_million_input_tokens`, `per_million_output_tokens` | tokens / 10^6 x price, input and output separately |
| TTS | characters synthesized, minus characters replayed from the phrase cache | `per_million_characters` | billed characters / 10^6 x price |

A stage costs:

- **`0`** when its provider is self-hosted (no per-call price; your hardware and power are
  real costs VoiceOS cannot see),
- **`None`, "not reported"** when the provider reported no usage or has no price,
- the computed amount otherwise.

### Per session

| `cost_status` | Meaning |
| --- | --- |
| `self_hosted` | Every stage runs on your own infrastructure |
| `complete` | Every stage has a cost (self-hosted stages count as 0) |
| `partial` | Some stages have a cost, some are not reported; the total covers only the known ones |
| `not_reported` | No stage has a cost |

`cost_total_usd` is the sum of the known stages, or `null` when none is known. The
dashboard never shows a missing cost as `$0.00`: it says "not reported" or "self-hosted".
Each session's `self_hosted_stages` lists which stages ran on your servers.

### Savings

What the caches avoided, at list price:

- characters replayed from the **phrase cache**, at the TTS provider's price,
- turns answered from the **response cache**, at this session's own average LLM cost per
  answered turn.

Savings are recorded per session (`savings_nusd`) and summed in the hourly rollup. A
self-hosted provider saves nothing in money (it has no price).

### Prices

Prices are whatever you enter for each provider: VoiceOS ships no price list, so a
number on the dashboard is always traceable to usage the provider reported and a price
someone configured. The dashboard and the API schema label costs as estimates.
