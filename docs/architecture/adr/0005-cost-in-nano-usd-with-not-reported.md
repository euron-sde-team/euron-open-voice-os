# ADR-0005: Cost in nano-USD, with an explicit "not reported"

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

A voice call's cost is the sum of tiny amounts (a fraction of a cent of audio, a few
hundred tokens, a few hundred characters) over three providers with different units.
Floats drift when such amounts are summed across thousands of sessions. Worse, a cost
dashboard that shows `$0.00` when a provider simply did not report usage, or when no price
was configured, is lying: it makes a hosted model look free.

## Decision

- Store money as integer nano-USD (`BIGINT`, 10^-9 USD), computed with `Decimal` and
  rounded up (`core/money.py`).
- Cost a stage only from usage its provider reported (audio seconds, tokens, characters)
  times a price configured on the provider. A missing usage report or a missing price makes
  that stage `None`, shown as "not reported".
- Self-hosted stages cost `0` and the session says `self_hosted`, not "free".
- A session's `cost_status` is `complete`, `partial`, `not_reported` or `self_hosted`; the
  total sums only known stages.
- VoiceOS ships no price list: every number traces to a price someone entered.

## Consequences

**Good**
- Totals are exact and auditable, and a missing number is visibly missing.
- Savings (phrase cache, response cache) are computed with the same prices, so they are
  as honest as the costs.

**Bad / caveats**
- Out of the box, hosted providers show "not reported" until an admin enters prices.
- Hardware and power for self-hosted stages are not modelled.

## Alternatives considered

- **Floats in USD**: drift on sums, rounding surprises in rollups.
- **A bundled vendor price table**: goes stale silently, and would let the product show
  numbers no one at the deployment chose.
