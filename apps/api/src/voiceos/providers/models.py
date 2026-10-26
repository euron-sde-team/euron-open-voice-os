"""Configured STT, LLM and TTS providers. API keys are sealed; the row keeps a hint only."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from voiceos.core.db import Base, TimestampMixin, new_id


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"
    __table_args__ = (CheckConstraint("stage IN ('stt', 'llm', 'tts')", name="ck_providers_stage"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    stage: Mapped[str] = mapped_column(String(8), nullable=False)
    adapter: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    model: Mapped[str | None] = mapped_column(String(120))
    voice: Mapped[str | None] = mapped_column(String(120))
    language: Mapped[str | None] = mapped_column(String(16))
    sealed_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_hint: Mapped[str | None] = mapped_column(String(16))
    # External: audio or text leaves your infrastructure; shown to users before a session.
    external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The admin's "treat as external" flag; ``external`` is derived from it, the adapter and
    # the URL, so it can be raised by hand but never lowered for a cloud or public endpoint.
    force_external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    self_hosted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timeout_s: Mapped[float] = mapped_column(Float, nullable=False, default=15.0)
    price: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
