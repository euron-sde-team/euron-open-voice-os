# Security Policy

VoiceOS hears your callers, sees their transcripts, and holds the API keys of the speech
and language model providers you connect, so we take reports seriously and respond
quickly.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.x (latest minor) | Yes |
| Older minors | No |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository ("Security" tab, "Report a vulnerability").

Please include:

- the affected component (`apps/api`, the runtime, the speech server, `apps/web`,
  `infra/terraform/...`) and version or commit,
- a description of the issue and its impact,
- steps to reproduce, or a proof of concept,
- any suggested mitigation.

What to expect:

| Stage | Target |
| ----- | ------ |
| Acknowledgement | within 3 business days |
| Initial assessment and severity | within 7 business days |
| Fix or mitigation for critical and high issues | within 30 days |
| Coordinated public disclosure | after a fix is released, credited to you unless you prefer otherwise |

## Scope

In scope: the code in this repository and the infrastructure it provisions with its
default settings. We are especially interested in:

- any way to connect to the voice runtime without a valid session token, to reuse a token,
  or to use a token for another agent or from another site,
- any way to start a session with an SDK key for an agent or origin outside its scope,
- any way to read another session's transcript, or a transcript past its retention,
- any way to recover a provider credential, an SDK key or a session secret from the API,
  the runtime, logs or the database,
- a provider that receives a caller's audio or text without the session disclosing it,
- making the runtime or a provider request reach an address it should not (instance
  metadata, link-local, the TURN relay reaching outside the VPC),
- authentication or authorization bypasses in the dashboard API.

Out of scope:

- **The demo seed.** `make demo` creates well-known demo accounts with the password from
  your local `.env`, on purpose.
- **The mock providers** (`apps/api/src/mockproviders`), a test fixture that is never
  deployed to AWS.
- Findings that require a compromised host, compromised AWS account, or leaked deployment
  secrets.
- Denial of service through resource exhaustion of a deployment you operate yourself.

## Hardening checklist for operators

See [docs/architecture/security.md](docs/architecture/security.md#operator-checklist).
