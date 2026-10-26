from decimal import Decimal

from voiceos.core.money import NUSD_PER_USD, nusd_to_usd, tokens_cost_nusd, usd_to_nusd


def test_usd_round_trip() -> None:
    assert usd_to_nusd("1") == NUSD_PER_USD
    assert usd_to_nusd(Decimal("0.000000001")) == 1
    assert nusd_to_usd(2_500_000_000) == 2.5


def test_usd_to_nusd_rounds_up() -> None:
    assert usd_to_nusd("0.0000000001") == 1


def test_tokens_cost_exact_and_rounded_up() -> None:
    # 1M tokens at $2.50 per million = $2.50
    assert tokens_cost_nusd(1_000_000, Decimal("2.5")) == 2_500_000_000
    # 1 token at $0.15 per million = 150 nUSD exactly
    assert tokens_cost_nusd(1, Decimal("0.15")) == 150
    # A fractional nano-dollar is rounded up, never down
    assert tokens_cost_nusd(1, Decimal("0.0001")) == 1


def test_zero_or_negative_tokens_cost_nothing() -> None:
    assert tokens_cost_nusd(0, Decimal(10)) == 0
    assert tokens_cost_nusd(-5, Decimal(10)) == 0
