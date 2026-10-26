"""Hourly usage rollups: what the overview reads instead of scanning sessions.

Written in the same transaction as the session they summarize, with an atomic upsert, so
the dashboard is exact at write time and stays fast however many sessions accumulate.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from voiceos.core.db import Base


class UsageHourly(Base):
    __tablename__ = "usage_hourly"

    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    # The agent id as text ("deleted" once removed), so history outlives agents.
    agent_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    transport: Mapped[str] = mapped_column(String(16), primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(120), nullable=False)
    sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    interruptions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stt_audio_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    llm_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    llm_output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tts_characters: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tts_characters_cached: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    response_cache_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_ms_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    response_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_nusd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    costed_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    savings_nusd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    external_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
