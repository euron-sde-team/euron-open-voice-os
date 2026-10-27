"""What a session cost, from measured usage and each provider's list prices.

Rules that keep the number honest:

* A stage costs ``None`` (not reported) when its usage was not reported or its provider has
  no price; it is never silently counted as zero.
* Self-hosted stages cost nothing per call, and the session says ``self_hosted`` rather
  than "free": hardware and power are real costs VoiceOS cannot see.
* Savings are what the caches avoided at list price: TTS characters replayed from the
  phrase cache, and LLM turns answered from the response cache (estimated at this
  session's own average LLM cost per turn).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from voiceos.core.contract import ProviderConfig, ResolvedAgent, SessionReport
from voiceos.core.money import tokens_cost_nusd


@dataclass(frozen=True, slots=True)
class Cost:
    stt: int | None
    llm: int | None
    tts: int | None
    total: int | None
    status: str  # complete | partial | not_reported | self_hosted
    savings: int


def _price(value: float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def stt_cost(p: ProviderConfig, audio_seconds: float) -> int | None:
    if p.self_hosted:
        return 0
    per_minute = _price(p.price.per_audio_minute)
    if per_minute is None:
        return None
    # per-minute price -> per-million-seconds price, reusing the integer rounding helper
    millis = round(audio_seconds * 1000)
    return tokens_cost_nusd(millis, per_minute * 1000 / 60)


def llm_cost(
    p: ProviderConfig, input_tokens: int, output_tokens: int, reported: bool
) -> int | None:
    if p.self_hosted:
        return 0
    pin, pout = _price(p.price.per_million_input_tokens), _price(p.price.per_million_output_tokens)
    if not reported or pin is None or pout is None:
        return None
    return tokens_cost_nusd(input_tokens, pin) + tokens_cost_nusd(output_tokens, pout)


def tts_cost(p: ProviderConfig, characters: int) -> int | None:
    if p.self_hosted:
        return 0
    per_million = _price(p.price.per_million_characters)
    if per_million is None:
        return None
    return tokens_cost_nusd(characters, per_million)


def session_cost(agent: ResolvedAgent | None, report: SessionReport) -> Cost:
    if agent is None:
        return Cost(None, None, None, None, "not_reported", 0)
    u = report.usage
    stt = stt_cost(agent.stt, u.stt_audio_seconds)
    llm = llm_cost(agent.llm, u.llm_input_tokens, u.llm_output_tokens, u.llm_usage_reported)
    small_used = agent.llm_small is not None and (
        u.llm_small_input_tokens or u.llm_small_output_tokens or u.llm_turns_routed_small
    )
    if agent.llm_small is not None and small_used:
        small = llm_cost(
            agent.llm_small,
            u.llm_small_input_tokens,
            u.llm_small_output_tokens,
            u.llm_usage_reported,
        )
        # Not reported for either model means the LLM stage as a whole is not reported.
        llm = None if llm is None or small is None else llm + small
    # TTS usage is counted when text is synthesized; phrase-cache replays never reach the
    # provider, so they are already outside it (and appear as savings instead).
    tts = tts_cost(agent.tts, u.tts_characters)
    parts = [stt, llm, tts]
    known = [p for p in parts if p is not None]
    total = sum(known) if known else None
    hosted = [agent.stt.self_hosted, agent.llm.self_hosted, agent.tts.self_hosted]
    if agent.llm_small is not None and small_used:
        hosted.append(agent.llm_small.self_hosted)
    if all(hosted):
        status = "self_hosted"
    elif all(p is not None for p in parts):
        status = "complete"
    elif known:
        status = "partial"
    else:
        status = "not_reported"

    savings = 0
    saved_tts = tts_cost(agent.tts, u.tts_characters_cached)
    if saved_tts:
        savings += saved_tts
    # Turns the LLM answered: a greeting is spoken without it, so it does not count.
    answered = len(
        [t for t in report.turns if t.user_text and t.agent_text and not t.response_cache_hit]
    )
    if llm and answered and u.response_cache_hits:
        savings += (llm // answered) * u.response_cache_hits
    return Cost(stt, llm, tts, total, status, savings)
