"""Process-wide services, built once in the app lifespan and shared by every request.

Holding them in one object (on ``app.state``) instead of module globals keeps the app
factory re-entrant and lets tests build an isolated container per app.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from voiceos.core.aws import aws_client
from voiceos.core.cache import ConfigCache
from voiceos.core.config import Settings
from voiceos.core.db import Database
from voiceos.core.kv import KV, create_kv
from voiceos.core.sealing import KeySealer, KmsSealer, LocalSealer
from voiceos.core.storage import LocalStorage, ObjectStorage, S3Storage


def build_http_client(timeout_s: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=5.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        follow_redirects=False,
    )


@dataclass
class Container:
    settings: Settings
    db: Database
    kv: KV
    # Outbound calls the control plane makes itself: provider connection tests.
    http: httpx.AsyncClient
    config_cache: ConfigCache
    sealer: KeySealer
    storage: ObjectStorage
    # key id -> when this process last wrote its last_used_at (bounded by the key count).
    key_touched: dict[uuid.UUID, datetime] = field(default_factory=dict)

    @classmethod
    def build(cls, settings: Settings) -> Container:
        kv = create_kv(settings.redis_url, settings.memory_cache_max_bytes)
        sealer: KeySealer = (
            KmsSealer(aws_client(settings, "kms"), settings.kms_key_id)
            if settings.key_mode == "kms"
            else LocalSealer(settings.local_master_key)
        )
        storage: ObjectStorage = (
            S3Storage(aws_client(settings, "s3"), settings.objects_bucket)
            if settings.storage == "s3"
            else LocalStorage(settings.local_storage_dir)
        )
        return cls(
            settings=settings,
            db=Database(
                settings.database_url,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
            ),
            kv=kv,
            http=build_http_client(10.0),
            config_cache=ConfigCache(kv),
            sealer=sealer,
            storage=storage,
        )

    async def close(self) -> None:
        await self.http.aclose()
        await self.kv.close()
        await self.db.dispose()
