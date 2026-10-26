"""The small, safe tool set an agent can enable.

``get_current_time`` and ``end_conversation`` need nothing. ``faq_lookup`` searches the
snippets attached to the agent (no network). ``http_webhook`` posts the call's arguments to
the one URL the agent's owner configured, never to a URL the model chooses.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import EndWorkerFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams

from voiceos.core.contract import ResolvedAgent, ToolSpec

# \w misses Indic vowel signs (matras), which would cut Hindi words into fragments, so
# the Indic blocks (Devanagari to Sinhala, less the danda punctuation) count as word characters.
_WORD = re.compile(r"[\w\u0900-\u0963\u0966-\u0dff]+", re.UNICODE)
# Question words that would make every snippet match.
_STOP = frozenset(
    [
        "the",
        "and",
        "are",
        "you",
        "your",
        "our",
        "for",
        "what",
        "when",
        "where",
        "which",
        "who",
        "how",
        "can",
        "does",
        "did",
        "with",
        "from",
        "this",
        "that",
        "there",
        "have",
        "has",
        "was",
        "were",
        "will",
        "would",
        "could",
        "should",
        "about",
        "into",
        "please",
        "tell",
    ]
)


def _term(word: str) -> str:
    """Lower-cased, with a plain English plural or tense ending folded ("Refunds", "refund")."""
    w = word.lower()
    if w.isascii():
        for suffix in ("ing", "es", "ed", "s"):
            if len(w) > len(suffix) + 3 and w.endswith(suffix):
                return w[: -len(suffix)]
    return w


def _terms(text: str) -> set[str]:
    return {_term(w) for w in _WORD.findall(text) if len(w) > 2 and w.lower() not in _STOP}


def faq_search(snippets: list[str], query: str, limit: int = 2) -> list[str]:
    """Snippets sharing the most words with the query (stable, no model needed)."""
    terms = _terms(query)
    if not terms:
        return []
    scored = [(len(terms & _terms(s)), i, s) for i, s in enumerate(snippets)]
    best = sorted((t for t in scored if t[0] > 0), key=lambda t: (-t[0], t[1]))
    return [s for _, _, s in best[:limit]]


Handler = Callable[[FunctionCallParams], Awaitable[None]]


def build_tools(
    agent: ResolvedAgent, *, on_end: Callable[[], None]
) -> list[FunctionSchema | Callable[..., Awaitable[Any]]]:
    tools: list[FunctionSchema | Callable[..., Awaitable[Any]]] = []
    for spec in agent.tools:
        tools.append(_tool(spec, agent, on_end))
    return tools


def _tool(spec: ToolSpec, agent: ResolvedAgent, on_end: Callable[[], None]) -> FunctionSchema:
    if spec.name == "get_current_time":

        async def now(params: FunctionCallParams) -> None:
            await params.result_callback({"utc": datetime.now(UTC).strftime("%H:%M UTC")})

        return FunctionSchema(
            "get_current_time", spec.description or "The current time in UTC.", {}, [], now
        )

    if spec.name == "end_conversation":

        async def end(params: FunctionCallParams) -> None:
            on_end()
            await params.result_callback({"ok": True})
            # Let the goodbye play, then end the session cleanly.
            await params.llm.push_frame(EndWorkerFrame(), FrameDirection.UPSTREAM)

        return FunctionSchema(
            "end_conversation",
            spec.description or "End the conversation after saying goodbye.",
            {},
            [],
            end,
        )

    if spec.name == "faq_lookup":

        async def lookup(params: FunctionCallParams) -> None:
            hits = faq_search(agent.faq, str(params.arguments.get("question", "")))
            await params.result_callback({"answers": hits or ["No matching answer."]})

        return FunctionSchema(
            "faq_lookup",
            spec.description or "Look up the answer to a question in this agent's FAQ.",
            {"question": {"type": "string", "description": "The caller's question"}},
            ["question"],
            lookup,
        )

    url = spec.url or ""

    async def webhook(params: FunctionCallParams) -> None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={"agent": agent.agent_id, **params.arguments})
            body: Any = resp.json() if "json" in resp.headers.get("content-type", "") else resp.text
            await params.result_callback({"status": resp.status_code, "body": body})
        except httpx.HTTPError as exc:
            await params.result_callback({"error": type(exc).__name__})

    return FunctionSchema(
        "http_webhook",
        spec.description or "Send the caller's request to the business system.",
        {"request": {"type": "string", "description": "What the caller wants"}},
        ["request"],
        webhook,
    )
