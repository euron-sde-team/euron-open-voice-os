# Architecture Decision Records

Each ADR captures one significant decision: the context that forced it, what we chose,
and what it costs us. ADRs are immutable once accepted. To revisit one, write a new ADR
that supersedes it.

| ADR | Decision | Status |
| --- | -------- | ------ |
| [0001](0001-pipecat-as-the-runtime.md) | Pipecat is the voice runtime; VoiceOS adds the control plane, measurement and policy around it | Accepted |
| [0002](0002-runtime-separate-from-control-plane.md) | The runtime is a separate service with no database: agents in, session reports out | Accepted |
| [0003](0003-local-speech-in-its-own-service.md) | Local Whisper and Kokoro run in their own service behind OpenAI-compatible endpoints | Accepted |
| [0004](0004-turn-on-ec2-behind-an-nlb.md) | The TURN relay runs on EC2 behind a network load balancer, not on Fargate | Accepted |
| [0005](0005-cost-in-nano-usd-with-not-reported.md) | Cost is integer nano-USD from reported usage, with an explicit "not reported" | Accepted |

**Template:** Status / Date, then Context, Decision, Consequences (good and bad), and
Alternatives considered.
