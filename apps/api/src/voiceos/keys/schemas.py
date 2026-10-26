from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field

from voiceos.core.schemas import ApiModel

ORIGIN = r"^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$"


class KeyIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    rpm_limit: int | None = Field(None, ge=1, le=1_000_000)
    agent_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    allowed_origins: list[Annotated[str, Field(pattern=ORIGIN, max_length=200)]] = Field(
        default_factory=list, max_length=20
    )
    expires_at: datetime | None = None


class KeyUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    rpm_limit: int | None = Field(None, ge=1, le=1_000_000)
    agent_ids: list[uuid.UUID] | None = Field(None, max_length=200)
    allowed_origins: list[Annotated[str, Field(pattern=ORIGIN, max_length=200)]] | None = Field(
        None, max_length=20
    )
    expires_at: datetime | None = None


class KeyOut(ApiModel):
    id: uuid.UUID
    name: str
    prefix: str
    display: str = Field(description="Safe identifier: vos_<prefix>_****")
    rpm_limit: int | None
    agent_ids: list[str]
    allowed_origins: list[str]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class KeyCreated(KeyOut):
    key: str = Field(description="The full key. Shown once; store it now")
