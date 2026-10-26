"""Prometheus metrics for the control plane (the runtime and the speech server have their own)."""

from __future__ import annotations

from prometheus_client import Counter

SESSIONS_STARTED = Counter("voiceos_sessions_started_total", "Session tickets issued", ["source"])
SESSIONS_REPORTED = Counter(
    "voiceos_sessions_reported_total", "Finished sessions stored", ["end_reason", "transport"]
)
TRANSCRIPTS_PURGED = Counter(
    "voiceos_transcripts_purged_total", "Session transcripts cleared by retention"
)
DEPENDENCY_ERRORS = Counter(
    "voiceos_dependency_errors_total", "Failed calls to a dependency", ["dependency", "operation"]
)
