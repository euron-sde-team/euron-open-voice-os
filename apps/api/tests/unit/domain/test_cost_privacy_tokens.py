"""Pure domain rules: session cost (AC9), redaction (AC7), session tokens (AC13),
provider classification (AC6) and the response cache key (AC15)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from voiceos.core.contract import (
    Price,
    ProviderConfig,
    ResolvedAgent,
    SessionReport,
    TurnReport,
    UsageReport,
)
from voiceos.core.tokens import AUDIENCE, issue, verify
from voiceos.privacy.redact import luhn_ok, redact, verhoeff_ok
from voiceos.providers.schemas import is_private_host
from voiceos.providers.service import classify
from voiceos.runtime.router import ResponseCache, normalize
from voiceos.sessions.cost import session_cost

SECRET = "unit-test-runtime-secret-with-32-plus-bytes"


def provider(stage: str, *, hosted: bool = False, **price: float) -> ProviderConfig:
    return ProviderConfig(
        provider_id=stage,
        name=f"{stage} provider",
        stage=stage,  # type: ignore[arg-type]
        adapter="openai_compatible",
        external=not hosted,
        self_hosted=hosted,
        price=Price(**price),
    )


def agent(stt: ProviderConfig, llm: ProviderConfig, tts: ProviderConfig) -> ResolvedAgent:
    return ResolvedAgent(
        agent_id="a1", version=3, name="A", system_prompt="x", stt=stt, llm=llm, tts=tts
    )


def report(usage: UsageReport, turns: list[TurnReport] | None = None) -> SessionReport:
    now = datetime.now(UTC)
    return SessionReport(
        session_id="s1",
        agent_id="a1",
        agent_version=3,
        transport="websocket",
        started_at=now,
        ended_at=now + timedelta(seconds=30),
        end_reason="client_left",
        usage=usage,
        turns=turns or [],
    )


USAGE = UsageReport(
    stt_audio_seconds=60.0,
    llm_input_tokens=1_000_000,
    llm_output_tokens=500_000,
    llm_usage_reported=True,
    tts_characters=2_000_000,
    tts_characters_cached=1_000_000,
)


# ── cost ─────────────────────────────────────────────────────────────────────────────
def test_every_stage_priced_and_reported_is_complete() -> None:
    a = agent(
        provider("stt", per_audio_minute=0.006),
        provider("llm", per_million_input_tokens=0.15, per_million_output_tokens=0.6),
        provider("tts", per_million_characters=15.0),
    )
    c = session_cost(a, report(USAGE))
    assert c.status == "complete"
    assert c.stt == 6_000_000  # $0.006 for one minute, in nano-USD
    assert c.llm == 150_000_000 + 300_000_000
    assert c.tts == 15_000_000_000  # only the million characters not replayed from cache
    assert c.total == c.stt + c.llm + c.tts
    assert c.savings == 15_000_000_000  # the cached million characters at list price


def test_a_missing_price_or_usage_is_not_reported_never_zero() -> None:
    a = agent(provider("stt"), provider("llm"), provider("tts"))
    c = session_cost(a, report(USAGE))
    assert (c.stt, c.llm, c.tts, c.total) == (None, None, None, None)
    assert c.status == "not_reported"

    priced_llm = provider("llm", per_million_input_tokens=1.0, per_million_output_tokens=1.0)
    unreported = USAGE.model_copy(update={"llm_usage_reported": False})
    c = session_cost(agent(provider("stt"), priced_llm, provider("tts")), report(unreported))
    assert c.llm is None and c.status == "not_reported"


def test_mixed_stages_are_partial_and_self_hosted_costs_nothing() -> None:
    a = agent(
        provider("stt", hosted=True),
        provider("llm", per_million_input_tokens=1.0, per_million_output_tokens=1.0),
        provider("tts"),
    )
    c = session_cost(a, report(USAGE))
    assert c.stt == 0 and c.tts is None and c.status == "partial"
    hosted = agent(
        provider("stt", hosted=True), provider("llm", hosted=True), provider("tts", hosted=True)
    )
    assert session_cost(hosted, report(USAGE)).status == "self_hosted"
    assert session_cost(None, report(USAGE)).status == "not_reported"


def test_response_cache_hits_count_as_llm_savings() -> None:
    a = agent(
        provider("stt", hosted=True),
        provider("llm", per_million_input_tokens=1.0, per_million_output_tokens=1.0),
        provider("tts", hosted=True),
    )
    now = datetime.now(UTC)
    turns = [
        TurnReport(index=0, started_at=now, user_text="q", agent_text="a"),
        TurnReport(index=1, started_at=now, user_text="q", agent_text="a", response_cache_hit=True),
    ]
    usage = USAGE.model_copy(update={"response_cache_hits": 1, "tts_characters_cached": 0})
    c = session_cost(a, report(usage, turns))
    assert c.savings == c.llm  # one answered turn paid for, one served from the cache


# ── redaction ────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail me at priya.s+demo@example.co.in please", "mail me at [email] please"),
        ("my PAN is ABCDE1234F", "my PAN is [pan]"),
        ("card 4111 1111 1111 1111 ok", "card [card] ok"),
        ("aadhaar 2345 6789 0124", "aadhaar [aadhaar]"),
        ("call +91 98765 43210 now", "call [phone] now"),
        ("table for 2 at 7pm", "table for 2 at 7pm"),
    ],
)
def test_personal_details_are_redacted(text: str, expected: str) -> None:
    assert redact(text) == expected


def test_checksums_decide_card_and_aadhaar() -> None:
    assert luhn_ok("4111111111111111") and not luhn_ok("4111111111111112")
    aadhaar = "2345" + "6789" + "0124"  # split so it never reads as an account id
    assert verhoeff_ok(aadhaar) and not verhoeff_ok(aadhaar[:-1] + "3")
    # A 16-digit number that fails Luhn is not called a card.
    assert redact("ref 4111 1111 1111 1112") != "ref [card]"
    assert redact(None) is None and redact("") == ""


# ── session tokens ───────────────────────────────────────────────────────────────────
def test_tokens_are_bound_short_lived_and_verified() -> None:
    token, claims = issue("agent-1", SECRET, subject="user:u1", origin="https://app.example.com")
    back = verify(token, SECRET)
    assert back == claims
    assert back is not None and back.agent_id == "agent-1"
    assert back.origin == "https://app.example.com"
    assert verify(token, "another-secret-with-32-plus-bytes-ok") is None
    assert verify("garbage", SECRET) is None
    expired = jwt.encode(
        {"sid": "s", "agent": "a", "sub": "x", "aud": AUDIENCE, "exp": int(time.time()) - 5},
        SECRET,
        algorithm="HS256",
    )
    assert verify(expired, SECRET) is None
    wrong_aud = jwt.encode(
        {"sid": "s", "agent": "a", "sub": "x", "aud": "other", "exp": int(time.time()) + 60},
        SECRET,
        algorithm="HS256",
    )
    assert verify(wrong_aud, SECRET) is None


# ── provider classification ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("adapter", "url", "marked", "expected"),
    [
        ("openai_compatible", "http://speech:8080/v1", False, (False, True)),
        ("openai_compatible", "http://10.0.3.7:11434/v1", False, (False, True)),
        ("openai_compatible", "http://10.0.3.7:11434/v1", True, (True, False)),
        ("openai_compatible", "https://api.openai.com/v1", False, (True, False)),
        ("deepgram", None, False, (True, False)),
        ("mock", "http://mock:4550/v1", False, (False, False)),
    ],
)
def test_external_is_derived_and_can_only_be_raised(
    adapter: str, url: str | None, marked: bool, expected: tuple[bool, bool]
) -> None:
    assert classify(adapter, url, marked) == expected


def test_private_hosts() -> None:
    for host in ("localhost", "127.0.0.1", "10.1.2.3", "192.168.1.5", "speech", "::1"):
        assert is_private_host(host), host
    for host in ("api.openai.com", "8.8.8.8"):
        assert not is_private_host(host), host


# ── response cache ───────────────────────────────────────────────────────────────────
def test_response_cache_keys_bind_agent_version_and_normalized_text() -> None:
    a = agent(provider("stt"), provider("llm"), provider("tts"))
    assert normalize("  What TIME do you open?! ") == "what time do you open"
    k = ResponseCache.key(a, "What time do you open?")
    assert k == ResponseCache.key(a, "what time do you open")
    assert k != ResponseCache.key(a.model_copy(update={"version": 4}), "what time do you open")


def test_response_cache_is_bounded_and_expires() -> None:
    cache = ResponseCache(max_entries=2, ttl_s=60)
    cache.put("a", "1")
    cache.put("b", "2")
    assert cache.get("a") == "1"  # a is now most recent
    cache.put("c", "3")
    assert cache.get("b") is None and cache.get("a") == "1" and cache.get("c") == "3"
    short = ResponseCache(ttl_s=-1)
    short.put("x", "y")
    assert short.get("x") is None
