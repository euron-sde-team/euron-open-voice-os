"""SDK keys: what a backend (or an embed, limited to its origins) presents to start sessions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from voiceos.core.db import Base, TimestampMixin, new_id


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rpm_limit: Mapped[int | None] = mapped_column(Integer)
    # Empty: every agent. Otherwise only these agents can be started with the key.
    agent_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Set for keys used from a web page (the embed): tokens bind to one of these origins.
    allowed_origins: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
