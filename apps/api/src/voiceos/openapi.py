"""Export the OpenAPI document. ``voiceos openapi > docs/api/openapi.yaml``."""

from __future__ import annotations

from typing import Any

from voiceos.core.config import Settings


def spec() -> dict[str, Any]:
    from voiceos.main import create_app

    app = create_app(Settings())
    document: dict[str, Any] = app.openapi()
    document["servers"] = [{"url": "http://localhost:4530", "description": "Local (make up)"}]
    return document


def to_yaml(document: dict[str, Any]) -> str:
    import yaml

    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100)
