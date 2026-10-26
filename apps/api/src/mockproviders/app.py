"""Deterministic stand-ins for cloud providers, for tests and the zero-key demo.

    POST /v1/chat/completions      OpenAI-compatible chat, streaming or not, with usage
    POST /v1/audio/transcriptions  returns the next scripted transcript (or a fixed one)
    POST /v1/audio/speech          streams a soft tone whose length follows the text
    POST /admin/faults             inject errors or delays per stage
    POST /admin/script             queue transcripts for the STT stand-in
    GET  /stats, POST /stats/reset what each stage received (to verify disclosure)

Answers are short, spoken-style and deterministic, so tests can assert on them. Nothing
here pretends to be a real model: the demo labels these providers "Mock".
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import struct
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

app = FastAPI(title="VoiceOS mock providers", docs_url=None, redoc_url=None)

_faults: dict[str, dict[str, Any]] = {}
_script: deque[str] = deque()
_stats: dict[str, Any] = {"chat": [], "stt": 0, "tts": [], "stt_bytes": 0}

TTS_RATE = 24_000

# Specific intents first, greetings last, so "hello, I would like to book" books.
_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\b(book|table|reservation|appointment)\b", re.I),
        "Sure. I have booked that for you. Is there anything else you need?",
    ),
    (
        re.compile(r"\b(open|opening|hours|close)\b", re.I),
        "On Sunday we open at ten in the morning and close at six in the evening.",
    ),
    (
        re.compile(r"\b(order|delivery|package)\b", re.I),
        "Your order shipped yesterday and should reach you tomorrow.",
    ),
    (re.compile(r"\b(time)\b", re.I), "I can check the time for you."),
    (
        re.compile(r"\b(weather)\b", re.I),
        "I cannot see the weather from here, but I hope it is pleasant.",
    ),
    (
        re.compile(r"\b(story|long)\b", re.I),
        " ".join(["This is a long answer that keeps going so you can interrupt it."] * 6),
    ),
    (re.compile(r"\b(bye|goodbye|thanks|thank you)\b", re.I), "Thank you for calling. Goodbye!"),
    (re.compile("[\\u0900-\\u097f]"), "नमस्ते! मैं आपकी कैसे मदद कर सकती हूँ?"),  # Devanagari
    (
        re.compile(r"\b(hello|hi|hey|namaste)\b", re.I),
        "Hello! I am the VoiceOS demo assistant. How can I help you today?",
    ),
]
_DEFAULT = "I heard you. This is a demo reply from the mock language model."


def _fault(stage: str) -> dict[str, Any] | None:
    fault = _faults.get(stage)
    if fault and fault.get("times", 1) > 0:
        if "times" in fault:
            fault["times"] -= 1
        return fault
    return None


async def _apply(stage: str) -> Response | None:
    fault = _fault(stage)
    if fault is None:
        return None
    if fault.get("delay_s"):
        await asyncio.sleep(float(fault["delay_s"]))
    if fault.get("status"):
        return JSONResponse(
            {"error": {"message": f"mock {stage} failure", "type": "api_error"}},
            status_code=int(fault["status"]),
        )
    return None


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def _answer(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
) -> tuple[str, dict[str, Any] | None]:
    last_user = next(
        (_text(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), ""
    )
    last = messages[-1] if messages else {}
    if last.get("role") == "tool":
        called = next(
            (
                c.get("function", {}).get("name")
                for m in reversed(messages)
                if m.get("role") == "assistant"
                for c in m.get("tool_calls") or []
            ),
            None,
        )
        if called == "end_conversation":
            return "Goodbye!", None
        if called == "faq_lookup":
            answers = json.loads(_text(last.get("content")) or "{}").get("answers") or ["nothing"]
            return f"Here is what I found: {answers[0]}", None
        return f"It is {_tool_result(_text(last.get('content')))}.", None
    names = {t.get("function", {}).get("name") for t in tools or []}
    if "get_current_time" in names and re.search(
        r"\b(what time is it|the time now|current time)\b", last_user, re.I
    ):
        return "", {"name": "get_current_time", "arguments": "{}"}
    if "faq_lookup" in names and re.search(r"\b(refund|policy|parking)\b", last_user, re.I):
        return "", {"name": "faq_lookup", "arguments": json.dumps({"question": last_user})}
    if "end_conversation" in names and re.search(r"\b(bye|goodbye)\b", last_user, re.I):
        return "", {"name": "end_conversation", "arguments": "{}"}
    for pattern, reply in _RULES:
        if pattern.search(last_user):
            return reply, None
    if not last_user:
        return "Hello! I am the VoiceOS demo assistant. How can I help you today?", None
    return _DEFAULT, None


def _tool_result(content: str) -> str:
    """A tool's JSON result read out as words: {"utc": "14:48 UTC"} -> 14:48 UTC."""
    try:
        value = json.loads(content)
    except ValueError:
        return content
    if isinstance(value, dict):
        return ", ".join(str(v) for v in value.values())
    return str(value)


def _tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


@app.post("/v1/chat/completions")
async def chat(request: Request) -> Response:
    if (failed := await _apply("llm")) is not None:
        return failed
    body = await request.json()
    messages = body.get("messages", [])
    _stats["chat"].append({"model": body.get("model"), "messages": len(messages)})
    reply, call = _answer(messages, body.get("tools"))
    prompt_tokens = sum(_tokens(_text(m.get("content"))) for m in messages)
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": _tokens(reply or "call"),
        "total_tokens": prompt_tokens + _tokens(reply or "call"),
    }
    created = int(time.time())
    model = body.get("model", "mock-llm")
    if not body.get("stream"):
        message: dict[str, Any] = {"role": "assistant", "content": reply or None}
        if call:
            message["tool_calls"] = [{"id": "call_1", "type": "function", "function": call}]
        return JSONResponse(
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if call else "stop",
                    }
                ],
                "usage": usage,
            }
        )

    async def events() -> AsyncIterator[str]:
        def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
            payload = {
                "id": "chatcmpl-mock",
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        yield chunk({"role": "assistant", "content": ""})
        slow = _faults.get("llm_stream", {}).get("delay_per_word_s", 0.0)
        if call:
            yield chunk(
                {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": call}]}
            )
            yield chunk({}, "tool_calls")
        else:
            for i, word in enumerate(reply.split(" ")):
                if slow:
                    await asyncio.sleep(float(slow))
                yield chunk({"content": (" " if i else "") + word})
            yield chunk({}, "stop")
        if body.get("stream_options", {}).get("include_usage"):
            yield f"data: {json.dumps({'id': 'chatcmpl-mock', 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [], 'usage': usage})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/v1/audio/transcriptions")
async def transcriptions(request: Request) -> Response:
    if (failed := await _apply("stt")) is not None:
        return failed
    form = await request.form()
    upload = form.get("file")
    size = len(await upload.read()) if upload is not None and hasattr(upload, "read") else 0
    _stats["stt"] += 1
    _stats["stt_bytes"] += size
    text = _script.popleft() if _script else "Hello there."
    return JSONResponse({"text": text})


def _tone(seconds: float) -> bytes:
    """A quiet 220 Hz tone with fades: audible in a demo, unmistakably not a voice."""
    n = int(seconds * TTS_RATE)
    fade = int(0.02 * TTS_RATE)
    out = bytearray()
    for i in range(n):
        env = min(1.0, i / fade, (n - i) / fade)
        out += struct.pack("<h", int(3000 * env * math.sin(2 * math.pi * 220 * i / TTS_RATE)))
    return bytes(out)


@app.post("/v1/audio/speech")
async def speech(request: Request) -> Response:
    if (failed := await _apply("tts")) is not None:
        return failed
    body = await request.json()
    text = str(body.get("input", ""))
    _stats["tts"].append({"voice": body.get("voice"), "chars": len(text)})
    seconds = min(20.0, 0.06 * len(text) + 0.2)
    audio = _tone(seconds)

    async def stream() -> AsyncIterator[bytes]:
        step = TTS_RATE // 5 * 2  # 200 ms per chunk
        for i in range(0, len(audio), step):
            yield audio[i : i + step]
            await asyncio.sleep(0)

    return StreamingResponse(stream(), media_type="audio/pcm")


@app.get("/v1/models")
async def models() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": "mock-llm", "object": "model"}]}


@app.post("/admin/faults")
async def set_faults(request: Request) -> dict[str, Any]:
    """Body: {"llm": {"status": 500, "times": 1}, "tts": {"delay_s": 30}, ...}; {} clears."""
    body = await request.json()
    _faults.clear()
    _faults.update(body)
    return {"faults": _faults}


@app.post("/admin/script")
async def set_script(request: Request) -> dict[str, Any]:
    body = await request.json()
    _script.clear()
    _script.extend(body.get("transcripts", []))
    return {"queued": len(_script)}


@app.get("/stats")
async def stats() -> dict[str, Any]:
    return _stats


@app.post("/stats/reset")
async def reset() -> dict[str, bool]:
    _stats.update({"chat": [], "stt": 0, "tts": [], "stt_bytes": 0})
    _faults.clear()
    _script.clear()
    return {"ok": True}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
