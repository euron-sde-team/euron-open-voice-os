"""The ``voiceos`` command: every service and admin task in one entry point."""

from __future__ import annotations

import argparse
import os
import sys


def _uvicorn(target: str, args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        target,
        factory=True,
        host=args.host,
        port=args.port,
        workers=1,  # one process per container: metrics and in-process state stay exact
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        access_log=False,
        log_config=None,
        timeout_graceful_shutdown=30,
    )


def _speech(args: argparse.Namespace) -> None:
    _uvicorn("voiceos.speech.app:create_app", args)


def _runtime(args: argparse.Namespace) -> None:
    _uvicorn("voiceos.runtime.app:create_app", args)


def _models(args: argparse.Namespace) -> None:
    from voiceos.speech.download import main

    main(["--dir", args.dir, "--whisper", args.whisper])


def _server(sub: argparse._SubParsersAction[argparse.ArgumentParser], name: str, fn: object, help_: str) -> None:
    p = sub.add_parser(name, help=help_)
    p.add_argument("--host", default="0.0.0.0")  # noqa: S104 containers listen on all interfaces
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    p.set_defaults(fn=fn)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="voiceos", description="Euron Open VoiceOS")
    sub = parser.add_subparsers(dest="command", required=True)
    _server(sub, "speech", _speech, "local speech server (Whisper and Kokoro)")
    _server(sub, "runtime", _runtime, "voice runtime (WebRTC and WebSocket sessions)")
    p = sub.add_parser("models", help="download the local speech models")
    p.add_argument("--dir", default=os.environ.get("SPEECH_MODELS_DIR", "./models"))
    p.add_argument("--whisper", default=os.environ.get("WHISPER_DOWNLOAD", "tiny,base,small"))
    p.set_defaults(fn=_models)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    args.fn(args)
