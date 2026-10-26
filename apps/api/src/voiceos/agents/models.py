"""Voice agents: prompt, providers per stage, and how they listen, speak, cache and retain."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from voiceos.core.db import Base, TimestampMixin, new_id


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    template: Mapped[str | None] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    greeting: Mapped[str | None] = mapped_column(String(500))
    # RESTRICT: a provider in use cannot be deleted out from under an agent.
    stt_provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    llm_provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    llm_small_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT")
    )
    tts_provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    voice: Mapped[str | None] = mapped_column(String(120))
    small_model_max_words: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    turn: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    privacy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cache: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    tools: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    faq: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    max_duration_s: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    idle_timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Bumped on every change: the runtime's cached config and the response cache key on it.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
