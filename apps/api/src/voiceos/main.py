"""Control plane application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from voiceos import __version__
from voiceos.agents.router import router as agents_router
from voiceos.analytics.router import router as analytics_router
from voiceos.audit.router import router as audit_router
from voiceos.auth.router import router as auth_router
from voiceos.benchmarks.router import router as benchmarks_router
from voiceos.core.config import Settings, get_settings
from voiceos.core.container import Container
from voiceos.core.db import import_all_models
from voiceos.core.errors import install_error_handlers
from voiceos.core.logs import configure_logging
from voiceos.core.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from voiceos.core.tracing import configure_tracing
from voiceos.internal.router import router as internal_router
from voiceos.keys.router import router as keys_router
from voiceos.providers.router import router as providers_router
from voiceos.sessions.router import router as sessions_router
from voiceos.sessions.router import sdk as sdk_router
from voiceos.system.router import router as system_router
from voiceos.users.router import router as users_router

DESCRIPTION = """
Control plane of a self-hosted real-time voice agent platform: agents, providers, session
tickets, conversation history with latency and cost, and analytics.

* `POST /v1/sessions` (SDK key, `Authorization: Bearer vos_...`): start a voice session
  with an agent. The ticket carries a one-minute token and the runtime URLs (WebRTC offer
  and WebSocket), plus the disclosure of any external provider.
* `/api/v1/*`: the dashboard API (session token from `POST /api/v1/auth/login`).

The voice runtime is a separate service; see the repository README.
"""


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    import_all_models()
    configure_logging(settings.log_level)
    configure_tracing(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or Container.build(settings)
        try:
            yield
        finally:
            if container is None:
                await app.state.container.close()

    app = FastAPI(
        title="Euron Open VoiceOS",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        separate_input_output_schemas=False,
    )
    install_error_handlers(app)
    for router in (
        sdk_router,
        auth_router,
        users_router,
        keys_router,
        providers_router,
        agents_router,
        sessions_router,
        analytics_router,
        benchmarks_router,
        audit_router,
        system_router,
        internal_router,
    ):
        app.include_router(router)

    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["authorization", "content-type", "x-voiceos-csrf", "x-request-id"],
        expose_headers=["x-request-id", "retry-after"],
        max_age=600,
    )
    app.add_middleware(BodySizeLimitMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware)
    return app
