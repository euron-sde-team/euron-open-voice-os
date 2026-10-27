"""Finished voice sessions, their turns, and the usage and cost they recorded.

A session row is written once, when the runtime reports the finished session (its id is the
session token's id, so a retried report is ignored). Turn text is stored only when the
agent's retention allows it, redacted first, and cleared by the worker when it expires.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from voiceos.core.db import Base, TimestampMixin


class VoiceSession(TimestampMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_started_at", text("started_at DESC")),
        Index("ix_sessions_agent_started", "agent_id", text("started_at DESC")),
        Index(
            "ix_sessions_transcript_expiry",
            "transcript_expires_at",
            postgresql_where=text("transcript_stored"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    agent_name: Mapped[str] = mapped_column(String(120), nullable=False)
    agent_version: Mapped[int] = mapped_column(Integer, nullable=False)
    transport: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    origin: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    end_reason: Mapped[str] = mapped_column(String(24), nullable=False)
    # Disclosure record: providers outside your infrastructure that received audio or text.
    external_providers: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    interruptions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_ms_p50: Mapped[float | None] = mapped_column(Float)
    response_ms_max: Mapped[float | None] = mapped_column(Float)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Nano-USD; None means a stage's usage or price was not reported (never shown as zero).
    cost_stt_nusd: Mapped[int | None] = mapped_column(BigInteger)
    cost_llm_nusd: Mapped[int | None] = mapped_column(BigInteger)
    cost_tts_nusd: Mapped[int | None] = mapped_column(BigInteger)
    cost_total_nusd: Mapped[int | None] = mapped_column(BigInteger)
    # complete | partial | not_reported | self_hosted
    cost_status: Mapped[str] = mapped_column(String(16), nullable=False)
    savings_nusd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    errors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    transcript_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transcript_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionTurn(Base):
    __tablename__ = "session_turns"
    __table_args__ = (Index("ix_session_turns_session", "session_id", "idx"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_text: Mapped[str | None] = mapped_column(Text)
    agent_text: Mapped[str | None] = mapped_column(Text)
    interrupted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_speech_ms: Mapped[float | None] = mapped_column(Float)
    endpoint_ms: Mapped[float | None] = mapped_column(Float)
    stt_ms: Mapped[float | None] = mapped_column(Float)
    llm_first_token_ms: Mapped[float | None] = mapped_column(Float)
    tts_first_audio_ms: Mapped[float | None] = mapped_column(Float)
    response_ms: Mapped[float | None] = mapped_column(Float)
    llm_model: Mapped[str | None] = mapped_column(String(120))
    llm_routed_small: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    response_cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(String(300))


class SessionClaim(Base):
    """A session token that has been used, across every runtime replica.

    Tokens live 60 seconds, so rows older than that only prove history; the worker deletes
    them after an hour."""

    __tablename__ = "session_claims"

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True
    )
