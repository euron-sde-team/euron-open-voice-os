# Privacy

VoiceOS hears people. These are the rules it follows by default, and where each one is
enforced.

## No audio is stored

There is no recording path in 0.1.0. Audio frames pass through the runtime's memory to
the STT provider and from the TTS provider to the caller, and are never written to the
database, object storage or logs. Opt-in recording is on the roadmap, not a hidden
setting. The tests check that a session leaves no objects in storage.

## No words in logs

Pipecat logs through loguru, and at its default DEBUG level it writes the language
model's whole context on every turn and every sentence it speaks: the caller's words,
outside retention, redaction and erasure. VoiceOS routes loguru into its JSON logger with a
WARNING floor (`core/logs.py`), so none of that is logged, and runs the redactor below over
every Pipecat message that does pass.

## Transcripts follow the agent's retention

`privacy.transcript_retention_days` on each agent (default 30):

- **0**: the words of a session are never stored. Timings, usage, cost and errors are.
- **N > 0**: the words are stored with `transcript_expires_at = ended_at + N days`, and the
  worker clears them when that passes (`sessions.service.purge_expired`, batches of 500).
  Timings and usage stay.

An admin can erase a session's words at any time (`DELETE
/api/v1/sessions/{id}/transcript`); the erase is audited.

## Personal details are redacted before storage

With `privacy.redact_pii` on (the default), `privacy/redact.py` replaces, before anything
is written:

| Detail | Rule | Replaced by |
| --- | --- | --- |
| E-mail address | pattern, written (`priya@example.com`) or as speech recognition writes it (`priya at gmail dot com`) | `[email]` |
| PAN (India) | five letters, four digits, one letter, in any case (`abcde1234f`), or spaced in capitals (`ABCDE 1234 F`) | `[pan]` |
| Aadhaar number | 12 digits, first not 0 or 1, valid Verhoeff checksum | `[aadhaar]` |
| Card number | 13 to 19 digits with a valid Luhn checksum | `[card]` |
| Phone number | 10 to 13 digits (spaces, dashes and a leading `+` allowed) that are not one of the above | `[phone]` |
| Other long number | 14 to 19 digits that fail the card checksum: a card number with one digit misheard is still a card number | `[number]` |

Checksums keep ordinary numbers ("table for 2 at 7") untouched, and shorter order and
booking numbers survive. Provider error messages stored on a session and its turns are
always redacted, since they can echo what the caller said. Redaction is pattern
based: names, addresses, and numbers spoken as words are not caught, which is why
retention is the stronger control.

Redaction happens in the control plane when the report is stored. The unredacted words
exist only in the runtime's memory during the call and in the report on its way to the
control plane over the private network.

## External processing is disclosed

A provider is **external** when audio or text leaves your infrastructure to reach it:

- the cloud adapters (Deepgram, Sarvam, Anthropic, ElevenLabs, Cartesia) always are,
- an OpenAI-compatible provider is external unless its URL is a loopback or private
  address or a single-label or `.local`, `.internal`, `.svc` host name,
- an admin can mark any provider external (`external: true`), but can never mark an
  external one self-hosted: the flag only raises the classification.

Before a call starts, the session ticket carries a disclosure ("This assistant sends your
audio or its transcript to ... to understand and answer you", or "Audio and transcripts
stay on this deployment's own servers"), which the Talk page shows next to the start
button and your app should show too. After the call, the session records
`external_providers`.

## What the browser contacts

Only the dashboard's origin and the runtime's. The Pipecat client is configured with its
local media manager, so no third-party script, CDN or telemetry endpoint is involved; the
Content-Security-Policy enforces it.
