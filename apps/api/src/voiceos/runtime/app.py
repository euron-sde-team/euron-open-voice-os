"""The voice runtime service.

    POST  /api/offer     WebRTC offer (SmallWebRTC); token in ?token= or requestData.token
    PATCH /api/offer     trickled ICE candidates for a known peer connection
    WS    /ws?token=     audio over WebSocket (Pipecat protobuf frames)
    GET   /api/ice       ICE servers with short-lived TURN credentials, for a session token
    GET   /healthz /readyz /metrics

Every connection needs a session token the control plane signed for one agent (see
``core/tokens.py``); each token starts at most one session. The runtime holds no database
connection: agents come from the control plane and finished sessions are reported back.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiortc import RTCIceServer
from fastapi import FastAPI, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from voiceos import __version__
from voiceos.core.config import RuntimeSettings, get_runtime_settings
from voiceos.core.contract import ResolvedAgent, SessionReport, Transport
from voiceos.core.logs import configure_logging
from voiceos.core.tokens import SessionClaims, verify
from voiceos.runtime.control import (
    AgentNotFoundError,
    ControlPlane,
    HttpControlPlane,
    StaticAgents,
)
from voiceos.runtime.pipeline import SessionShared, run_session

log = logging.getLogger("voiceos.runtime")

SESSIONS_ACTIVE = Gauge("voiceos_runtime_sessions_active", "Voice sessions in progress")
SESSIONS = Counter("voiceos_runtime_sessions_total", "Finished sessions", ["transport", "end"])
REJECTED = Counter("voiceos_runtime_rejected_total", "Refused connections", ["reason"])
RESPONSE_MS = Histogram(
    "voiceos_runtime_response_seconds",
    "User stopped speaking to agent audio, per turn",
    buckets=(0.3, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 10),
)


class RejectedError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class Live:
    claims: SessionClaims
    transport: Transport
    task: asyncio.Task[SessionReport] | None = None
    pc_id: str | None = None


class Sessions:
    """Admission control: token checks, single use, per-instance cap."""

    def __init__(self, settings: RuntimeSettings) -> None:
        self.settings = settings
        self.live: dict[str, Live] = {}
        self._used: dict[str, float] = {}

    def admit(self, token: str | None, origin: str | None, transport: Transport) -> SessionClaims:
        if not token:
            raise RejectedError(
                401, "missing_token", "Connect with a session token from the VoiceOS API"
            )
        claims = verify(token, self.settings.runtime_token_secret)
        if claims is None:
            raise RejectedError(401, "invalid_token", "The session token is invalid or expired")
        if claims.origin and origin and claims.origin != origin:
            raise RejectedError(403, "origin_mismatch", "This token was issued for another site")
        now = time.monotonic()
        self._used = {sid: t for sid, t in self._used.items() if t > now}
        if claims.session_id in self._used or claims.session_id in self.live:
            raise RejectedError(409, "token_used", "This session token was already used")
        if len(self.live) >= self.settings.max_sessions:
            raise RejectedError(
                503, "runtime_busy", "Every voice slot on this instance is busy. Try again shortly"
            )
        self._used[claims.session_id] = now + 120
        self.live[claims.session_id] = Live(claims, transport)
        SESSIONS_ACTIVE.set(len(self.live))
        return claims

    def release(self, session_id: str) -> None:
        self.live.pop(session_id, None)
        SESSIONS_ACTIVE.set(len(self.live))


def turn_credentials(secret: str, ttl_s: int = 3600, label: str = "voiceos") -> tuple[str, str]:
    """coturn ``use-auth-secret`` credentials: valid until ``ttl_s`` from now, per caller."""
    username = f"{int(time.time()) + ttl_s}:{label}"
    digest = hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()
    return username, base64.b64encode(digest).decode()


def create_app(
    settings: RuntimeSettings | None = None, control: ControlPlane | None = None
) -> FastAPI:
    settings = settings or get_runtime_settings()
    configure_logging(settings.log_level)
    if control is None:
        import os

        static = os.environ.get("RUNTIME_STATIC_AGENTS")
        control = (
            StaticAgents(static)
            if static
            else HttpControlPlane(
                settings.control_plane_url,
                settings.internal_api_token,
                ttl_s=settings.agent_cache_ttl_s,
                timeout_s=settings.report_timeout_s,
            )
        )
    sessions = Sessions(settings)
    shared = SessionShared()

    def ice(label: str) -> list[dict[str, Any]]:
        if not settings.ice_urls:
            return []
        user, cred = (
            turn_credentials(settings.turn_password, label=label)
            if settings.turn_password
            else ("", "")
        )
        return [{"urls": settings.ice_urls, "username": user, "credential": cred}]

    server_ice = [
        RTCIceServer(urls=s["urls"], username=s["username"], credential=s["credential"])
        for s in ice("runtime")
    ]
    webrtc = SmallWebRTCRequestHandler(ice_servers=server_ice or None)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        for live in list(sessions.live.values()):
            if live.task:
                live.task.cancel()
        await webrtc.close()  # type: ignore[no-untyped-call]
        await control.close()

    app = FastAPI(
        title="Euron Open VoiceOS runtime",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.sessions = sessions
    app.state.control = control
    app.state.shared = shared
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["authorization", "content-type"],
        max_age=600,
    )

    @app.exception_handler(RejectedError)
    async def _rejected(_: Request, exc: RejectedError) -> JSONResponse:
        REJECTED.labels(exc.code).inc()
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status
        )

    async def load_agent(claims: SessionClaims) -> ResolvedAgent:
        try:
            return await control.agent(claims.agent_id)
        except AgentNotFoundError:
            sessions.release(claims.session_id)
            raise RejectedError(
                404, "unknown_agent", "This agent does not exist or is disabled"
            ) from None
        except Exception:
            sessions.release(claims.session_id)
            log.exception("agent load failed", extra={"agent_id": claims.agent_id})
            raise RejectedError(
                503, "control_plane_unavailable", "The VoiceOS API is unreachable"
            ) from None

    async def run(
        claims: SessionClaims, agent: ResolvedAgent, transport: Any, kind: Transport
    ) -> SessionReport:
        try:
            report = await run_session(
                agent=agent,
                transport=transport,
                transport_kind=kind,
                session_id=claims.session_id,
                shared=shared,
            )
            report = report.model_copy(update={"subject": claims.subject, "origin": claims.origin})
        except asyncio.CancelledError:
            report = SessionReport(
                session_id=claims.session_id,
                agent_id=agent.agent_id,
                agent_version=agent.version,
                transport=kind,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                end_reason="shutdown",
                external_providers=agent.external_providers(),
                subject=claims.subject,
                origin=claims.origin,
            )
        finally:
            sessions.release(claims.session_id)
        SESSIONS.labels(kind, report.end_reason).inc()
        for turn in report.turns:
            if turn.response_ms is not None:
                RESPONSE_MS.observe(turn.response_ms / 1000)
        await control.report(report)
        return report

    # ── WebRTC ──────────────────────────────────────────────────────────────────────
    @app.post("/api/offer")
    async def offer(request: Request, token: str | None = Query(None)) -> dict[str, Any] | None:
        body = await request.json()
        req = SmallWebRTCRequest.from_dict(dict(body))
        data = req.request_data if isinstance(req.request_data, dict) else {}
        if req.pc_id and any(lv.pc_id == req.pc_id for lv in sessions.live.values()):
            # Renegotiation (ICE restart) of a live connection: same session, no new token.
            return await webrtc.handle_web_request(req, _no_new_connection)
        claims = sessions.admit(token or data.get("token"), request.headers.get("origin"), "webrtc")
        agent = await load_agent(claims)

        async def on_connection(connection: SmallWebRTCConnection) -> None:
            transport = SmallWebRTCTransport(
                webrtc_connection=connection,
                params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
            )
            sessions.live[claims.session_id].task = asyncio.create_task(
                run(claims, agent, transport, "webrtc")
            )

        try:
            answer = await webrtc.handle_web_request(req, on_connection)
        except Exception:
            sessions.release(claims.session_id)
            raise RejectedError(
                400, "bad_offer", "The WebRTC offer could not be answered"
            ) from None
        if answer and claims.session_id in sessions.live:
            sessions.live[claims.session_id].pc_id = answer.get("pc_id")
        return answer

    @app.patch("/api/offer")
    async def candidates(request: Request) -> dict[str, bool]:
        body = await request.json()
        await webrtc.handle_patch_request(
            SmallWebRTCPatchRequest(
                pc_id=body["pc_id"],
                candidates=[_candidate(c) for c in body.get("candidates", [])],
            )
        )
        return {"ok": True}

    @app.get("/api/ice")
    async def ice_servers(token: str = Query(...)) -> dict[str, Any]:
        claims = verify(token, settings.runtime_token_secret)
        if claims is None:
            raise RejectedError(401, "invalid_token", "The session token is invalid or expired")
        return {"iceServers": ice(claims.session_id[:8])}

    # ── WebSocket ───────────────────────────────────────────────────────────────────
    @app.websocket("/ws")
    async def ws(websocket: WebSocket, token: str | None = Query(None)) -> None:
        origin = websocket.headers.get("origin")
        if origin and origin not in settings.allowed_origins:
            REJECTED.labels("origin").inc()
            await websocket.close(code=4403, reason="origin not allowed")
            return
        try:
            claims = sessions.admit(token, origin, "websocket")
            agent = await load_agent(claims)
        except RejectedError as exc:
            REJECTED.labels(exc.code).inc()
            await websocket.close(code=4000 + exc.status, reason=exc.code)
            return
        await websocket.accept()
        transport = FastAPIWebsocketTransport(
            websocket,
            FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                add_wav_header=False,
                serializer=ProtobufFrameSerializer(),
                session_timeout=agent.max_duration_s,
            ),
        )
        task = asyncio.create_task(run(claims, agent, transport, "websocket"))
        sessions.live[claims.session_id].task = task
        await task

    # ── Ops ─────────────────────────────────────────────────────────────────────────
    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        busy = len(sessions.live) >= settings.max_sessions
        return JSONResponse(
            {
                "status": "busy" if busy else "ready",
                "sessions": len(sessions.live),
                "capacity": settings.max_sessions,
            },
            status_code=503 if busy else 200,
        )

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


async def _no_new_connection(_: SmallWebRTCConnection) -> None:
    """Renegotiation reuses the existing connection; nothing new to start."""


def _candidate(c: dict[str, Any]) -> Any:
    from pipecat.transports.smallwebrtc.request_handler import IceCandidate

    return IceCandidate(
        candidate=c.get("candidate", ""),
        sdp_mid=c.get("sdp_mid", c.get("sdpMid", "")),
        sdp_mline_index=int(c.get("sdp_mline_index", c.get("sdpMLineIndex", 0))),
    )
