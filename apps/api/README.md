# VoiceOS server packages

One Python project, several services (each container installs only its extras):

| Service | Command | Extras |
| --- | --- | --- |
| Control plane API | `voiceos serve` | none |
| Worker | `voiceos worker` | none |
| Voice runtime | `voiceos runtime` | `runtime` |
| Local speech (Whisper, Kokoro) | `voiceos speech` | `speech` |
| Mock providers (tests, zero-key demo) | `uvicorn mockproviders.app:app` | none |

See the repository README for setup.
