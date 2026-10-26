"""The voiceos command dispatches each service and task to the right entry point."""

from __future__ import annotations

import sys
from typing import Any

import pytest

from voiceos import cli


def test_servers_start_the_right_app_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[tuple[str, dict[str, Any]]] = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda target, **kw: started.append((target, kw)))
    cli.main(["serve", "--port", "4530"])
    cli.main(["runtime"])
    cli.main(["speech", "--host", "127.0.0.1"])
    assert [t for t, _ in started] == [
        "voiceos.main:create_app",
        "voiceos.runtime.app:create_app",
        "voiceos.speech.app:create_app",
    ]
    serve = started[0][1]
    assert serve["factory"] is True and serve["port"] == 4530 and serve["workers"] == 1


def test_tasks_reach_their_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    from voiceos.migrations import runner
    from voiceos.speech import download

    calls: list[Any] = []
    monkeypatch.setattr(runner, "upgrade", lambda url: calls.append(("upgrade", url)))
    monkeypatch.setattr(runner, "revision", lambda url, msg: calls.append(("revision", msg)))
    monkeypatch.setattr(download, "main", lambda argv: calls.append(("models", argv)))

    async def worker_main() -> None:
        calls.append(("worker",))

    import voiceos.worker

    monkeypatch.setattr(voiceos.worker, "main", worker_main)
    cli.main(["migrate"])
    cli.main(["revision", "-m", "add things"])
    cli.main(["models", "--dir", "./models-test", "--whisper", "base"])
    cli.main(["worker"])
    assert [c[0] for c in calls] == ["upgrade", "revision", "models", "worker"]
    assert calls[1] == ("revision", "add things")
    assert calls[2] == ("models", ["--dir", "./models-test", "--whisper", "base"])


def test_openapi_prints_the_contract(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["openapi"])
    out = capsys.readouterr().out
    assert out.startswith("openapi: 3.1.0")
    assert "/v1/sessions:" in out and "Euron Open VoiceOS" in out


def test_a_weak_owner_password_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICEOS_OWNER_PASSWORD", "short")
    with pytest.raises(SystemExit, match="password needs"):
        cli.main(["create-owner", "--email", "a@example.test"])


def test_an_unknown_command_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["voiceos", "nonsense"])
    with pytest.raises(SystemExit):
        cli.main()
