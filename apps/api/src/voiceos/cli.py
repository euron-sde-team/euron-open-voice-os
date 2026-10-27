"""The ``voiceos`` command: every service and admin task in one entry point."""

from __future__ import annotations

import argparse
import asyncio
import getpass
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
        # Only trust X-Forwarded-For from the load balancer's network (the VPC CIDR on AWS).
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        access_log=False,
        log_config=None,
        timeout_graceful_shutdown=30,
    )


def _serve(args: argparse.Namespace) -> None:
    _uvicorn("voiceos.main:create_app", args)


def _speech(args: argparse.Namespace) -> None:
    _uvicorn("voiceos.speech.app:create_app", args)


def _runtime(args: argparse.Namespace) -> None:
    _uvicorn("voiceos.runtime.app:create_app", args)


def _worker(_: argparse.Namespace) -> None:
    from voiceos.worker import main

    asyncio.run(main())


def _models(args: argparse.Namespace) -> None:
    from voiceos.speech.download import main

    mirrors = [m for m in args.mirror.split(",") if m]
    main(["--dir", args.dir, "--whisper", args.whisper, *(f"--mirror={m}" for m in mirrors)])


def _migrate(_: argparse.Namespace) -> None:
    from voiceos.core.config import get_settings
    from voiceos.migrations.runner import upgrade

    upgrade(get_settings().database_url)
    print("migrations applied")


def _revision(args: argparse.Namespace) -> None:
    from voiceos.core.config import get_settings
    from voiceos.migrations.runner import revision

    revision(get_settings().database_url, args.message)


async def _create_owner(email: str, name: str, password: str) -> None:
    from sqlalchemy import func, select

    from voiceos.core.config import get_settings
    from voiceos.core.db import Database, import_all_models
    from voiceos.core.security import hash_password, password_problems
    from voiceos.users.models import User

    if problems := password_problems(password):
        sys.exit("password needs " + ", ".join(problems))
    import_all_models()
    db = Database(get_settings().database_url, pool_size=1, max_overflow=0)
    try:
        async with db.sessionmaker() as session:
            existing = await session.scalar(
                select(User).where(func.lower(User.email) == email.lower())
            )
            if existing:
                existing.role = "owner"
                existing.password_hash = hash_password(password)
                existing.disabled = False
                existing.session_version += 1
                print(f"updated {email} (owner)")
            else:
                session.add(
                    User(
                        email=email.lower(),
                        name=name,
                        role="owner",
                        password_hash=hash_password(password),
                    )
                )
                print(f"created {email} (owner)")
            await session.commit()
    finally:
        await db.dispose()


def _owner(args: argparse.Namespace) -> None:
    password = os.environ.get("VOICEOS_OWNER_PASSWORD") or getpass.getpass("Password: ")
    asyncio.run(_create_owner(args.email, args.name, password))


def _seed(args: argparse.Namespace) -> None:
    from voiceos.demo.seed import run

    asyncio.run(run(conversations=args.conversations))


def _openapi(_: argparse.Namespace) -> None:
    from voiceos.openapi import spec, to_yaml

    sys.stdout.write(to_yaml(spec()))


def _server(
    sub: argparse._SubParsersAction[argparse.ArgumentParser], name: str, fn: object, help_: str
) -> None:
    p = sub.add_parser(name, help=help_)
    p.add_argument("--host", default="0.0.0.0")  # noqa: S104 containers listen on all interfaces
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    p.set_defaults(fn=fn)


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    if argv[:1] == ["wer"]:
        from voiceos.benchmarks.wer import main as wer

        wer(argv[1:])
        return
    parser = argparse.ArgumentParser(prog="voiceos", description="Euron Open VoiceOS")
    sub = parser.add_subparsers(dest="command", required=True)
    _server(sub, "serve", _serve, "control plane API")
    _server(sub, "runtime", _runtime, "voice runtime (WebRTC and WebSocket sessions)")
    _server(sub, "speech", _speech, "local speech server (Whisper and Kokoro)")
    sub.add_parser("worker", help="retention purge and benchmark runs").set_defaults(fn=_worker)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(fn=_migrate)
    p = sub.add_parser("revision", help="autogenerate a migration from the models")
    p.add_argument("-m", "--message", required=True)
    p.set_defaults(fn=_revision)
    p = sub.add_parser("create-owner", help="create or reset an owner account")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Owner")
    p.set_defaults(fn=_owner)
    p = sub.add_parser("models", help="download the local speech models")
    p.add_argument("--dir", default=os.environ.get("SPEECH_MODELS_DIR", "./models"))
    p.add_argument("--whisper", default=os.environ.get("WHISPER_DOWNLOAD", "tiny,base,small"))
    p.add_argument(
        "--mirror",
        default=os.environ.get("KOKORO_MIRROR", ""),
        help="comma separated base URLs holding the Kokoro files, tried first",
    )
    p.set_defaults(fn=_models)
    p = sub.add_parser("seed-demo", help="demo providers, agents and real recorded conversations")
    p.add_argument("--conversations", type=int, default=12)
    p.set_defaults(fn=_seed)
    # Listed here for --help; its own options are parsed by voiceos.benchmarks.wer.
    sub.add_parser(
        "wer", help="word error rate on FLEURS through the speech service", add_help=False
    )
    sub.add_parser("openapi", help="print the OpenAPI document as YAML").set_defaults(fn=_openapi)
    args = parser.parse_args(argv)
    args.fn(args)
