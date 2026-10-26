"""Session tokens: the control plane signs, the voice runtime verifies.

A browser (or an SDK) asks the control plane for a session; the control plane checks the
caller may use that agent and returns a short-lived token bound to the agent, the session
id and, for browsers, the page origin. The runtime accepts a connection only with a valid
token, and each token starts at most one session.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

AUDIENCE = "voiceos-runtime"
TTL = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class SessionClaims:
    session_id: str
    agent_id: str
    origin: str | None
    subject: str  # "user:<id>" or "key:<id>", for the audit trail


def issue(agent_id: str, secret: str, *, subject: str, origin: str | None = None) -> tuple[str, SessionClaims]:
    claims = SessionClaims(str(uuid.uuid4()), agent_id, origin, subject)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sid": claims.session_id,
            "agent": agent_id,
            "origin": origin,
            "sub": subject,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + TTL,
        },
        secret,
        algorithm="HS256",
    )
    return token, claims


def verify(token: str, secret: str) -> SessionClaims | None:
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"], audience=AUDIENCE)
        return SessionClaims(str(data["sid"]), str(data["agent"]), data.get("origin"), str(data["sub"]))
    except (jwt.PyJWTError, KeyError):
        return None
