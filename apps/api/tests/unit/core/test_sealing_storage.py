import uuid

import pytest
from cryptography.exceptions import InvalidTag

from voiceos.core.sealing import LocalSealer
from voiceos.core.storage import LocalStorage, ObjectNotFoundError


async def test_local_sealer_round_trip_and_context_binding() -> None:
    # Upstream keys are sealed with the upstream row's id as context, so a sealed key copied
    # onto another upstream's row cannot be opened there.
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    sealer = LocalSealer("test-only-master-key")
    sealed = await sealer.seal("sk-secret", first)
    assert b"sk-secret" not in sealed
    assert await sealer.open(sealed, first) == "sk-secret"
    with pytest.raises(InvalidTag):
        await sealer.open(sealed, second)


async def test_local_sealer_uses_fresh_nonces() -> None:
    sealer = LocalSealer("test-only-master-key")
    assert await sealer.seal("same", "c") != await sealer.seal("same", "c")


async def test_local_sealer_rejects_wrong_key_and_format() -> None:
    sealed = await LocalSealer("key-a").seal("v", "c")
    with pytest.raises(InvalidTag):
        await LocalSealer("key-b").open(sealed, "c")
    with pytest.raises(ValueError, match="unknown sealed format"):
        await LocalSealer("key-a").open(b"\x09" + sealed[1:], "c")


async def test_local_storage_round_trip(tmp_path: object) -> None:
    storage = LocalStorage(str(tmp_path))
    await storage.put("jobs/a/payload.json", b"{}", "application/json")
    assert await storage.get("jobs/a/payload.json") == b"{}"
    with pytest.raises(ObjectNotFoundError):
        await storage.get("jobs/missing.json")


async def test_local_storage_refuses_path_traversal(tmp_path: object) -> None:
    storage = LocalStorage(str(tmp_path))
    with pytest.raises(ValueError, match="escapes"):
        await storage.put("../outside.txt", b"x", "text/plain")
