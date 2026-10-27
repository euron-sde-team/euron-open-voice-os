"""One voice session: transport in, VAD and turn detection, STT, LLM, TTS, transport out.

    transport.input ─► STT ─► user turn (Silero VAD + Smart Turn v3) ─► TurnRouter
        ─► LLM (or LLMSwitcher: main / small) ─► TTS (phrase cache) ─► transport.output
        ─► assistant turn

``run_session`` builds that pipeline from a ``ResolvedAgent`` and runs it until the client
leaves, the agent ends the call, the session idles out, reaches its maximum length, or
fails. It always returns a ``SessionReport`` built from what was measured.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    Frame,
    LLMRunFrame,
    TTSSpeakFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.pipeline.llm_switcher import LLMSwitcher
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.transports.base_transport import BaseTransport
from pipecat.turns.user_start.min_words_user_turn_start_strategy import (
    MinWordsUserTurnStartStrategy,
)
from pipecat.turns.user_start.transcription_user_turn_start_strategy import (
    TranscriptionUserTurnStartStrategy,
)
from pipecat.turns.user_start.vad_user_turn_start_strategy import VADUserTurnStartStrategy
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (
    SpeechTimeoutUserTurnStopStrategy,
)
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from voiceos.core.contract import EndReason, ResolvedAgent, SessionReport, Transport
from voiceos.runtime.providers import Resources, build_llm, build_stt, build_tts
from voiceos.runtime.router import ResponseCache, TurnRouter
from voiceos.runtime.services.phrase_cache import PhraseCache
from voiceos.runtime.tools import build_tools
from voiceos.runtime.turns import TurnRecorder

log = logging.getLogger("voiceos.runtime")

FALLBACK_STT = "Sorry, I did not catch that. Could you say it again?"
FALLBACK_LLM = "Sorry, I am having trouble answering right now. Please try again in a moment."


@dataclass
class SessionShared:
    """Per-process state every session uses (caches)."""

    phrase_cache: PhraseCache = field(default_factory=PhraseCache)
    response_cache: ResponseCache = field(default_factory=ResponseCache)


def _turn_strategies(agent: ResolvedAgent) -> UserTurnStrategies:
    t = agent.turn
    interrupt = t.allow_interruptions
    start: list[Any]
    if interrupt and t.interruption_min_words > 1:
        start = [MinWordsUserTurnStartStrategy(min_words=t.interruption_min_words)]
    else:
        start = [
            VADUserTurnStartStrategy(enable_interruptions=interrupt),
            TranscriptionUserTurnStartStrategy(enable_interruptions=interrupt),
        ]
    stop: list[Any] = (
        [TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())]
        if t.mode == "smart"
        else [SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=t.vad_stop_secs)]
    )
    return UserTurnStrategies(start=start, stop=stop)


async def run_session(
    *,
    agent: ResolvedAgent,
    transport: BaseTransport,
    transport_kind: Transport,
    session_id: str,
    shared: SessionShared,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> SessionReport:
    started_at = datetime.now(UTC)
    recorder = TurnRecorder()
    resources = Resources()
    end_reason: list[EndReason] = []

    def end(reason: EndReason) -> None:
        if not end_reason:
            end_reason.append(reason)

    try:
        stt = build_stt(agent.stt, agent.language)
        main_llm = build_llm(agent.llm, agent.system_prompt)
        small_llm = build_llm(agent.llm_small, agent.system_prompt) if agent.llm_small else None
        recorder.small_processor = small_llm.name if small_llm else None
        tts = build_tts(
            agent.tts,
            resources,
            shared.phrase_cache if agent.cache.tts_phrase_cache else None,
            agent.language,
        )
    except Exception as exc:
        await resources.close()
        log.warning("session rejected: provider setup failed", extra={"error": str(exc)[:200]})
        return _report(agent, session_id, transport_kind, started_at, "error", recorder, [str(exc)])

    try:
        llm_stage: Any = LLMSwitcher(llms=[main_llm, small_llm]) if small_llm else main_llm
        tools = build_tools(agent, on_end=lambda: end("agent_ended"))
        context = LLMContext(tools=tools) if tools else LLMContext()
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(
                    params=VADParams(stop_secs=agent.turn.vad_stop_secs)
                ),
                user_turn_strategies=_turn_strategies(agent),
                user_turn_stop_timeout=agent.turn.transcript_wait_s,
            ),
        )
        router = TurnRouter(
            agent,
            recorder,
            shared.response_cache,
            main_llm=main_llm if small_llm else None,
            small_llm=small_llm,
        )
        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                user_aggregator,
                router,
                llm_stage,
                tts,
                transport.output(),
                assistant_aggregator,
            ]
        )
        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
            idle_timeout_secs=agent.idle_timeout_s,
            observers=[recorder, _AnswerStore(recorder, router)],
            processor_unusable_policy=ProcessorUnusablePolicy.END,
        )
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
    except Exception as exc:
        # Setup past the providers failed (VAD, aggregators, the worker): free what was
        # opened and still report the session, so it never vanishes.
        await resources.close()
        log.exception("session setup failed", extra={"session_id": session_id})
        return _report(
            agent, session_id, transport_kind, started_at, "error", recorder, [type(exc).__name__]
        )

    @transport.event_handler("on_client_connected")
    async def _connected(_transport: Any, _client: Any) -> None:
        if agent.greeting:
            recorder.start_greeting(agent.greeting)
            await worker.queue_frames([TTSSpeakFrame(agent.greeting)])
        else:
            await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def _disconnected(_transport: Any, _client: Any) -> None:
        end("client_left")
        await runner.cancel()

    @worker.event_handler("on_idle_timeout")
    async def _idle(_worker: Any) -> None:
        end("idle_timeout")

    @worker.event_handler("on_pipeline_error")
    async def _error(_worker: Any, frame: Any) -> None:
        # A provider failed: say so out loud when the voice still works, and keep going.
        # Matched by identity, not by name: "OpenAISTTService" contains "TTS".
        failed = getattr(frame, "processor", None)
        message = str(getattr(frame, "error", frame))[:200]
        if on_event:
            on_event({"type": "provider_error", "message": message})
        if failed is tts:
            return
        spoken = FALLBACK_STT if failed is stt else FALLBACK_LLM
        await worker.queue_frames([TTSSpeakFrame(spoken)])

    async def max_duration() -> None:
        await asyncio.sleep(agent.max_duration_s)
        end("max_duration")
        await runner.cancel()

    limiter = asyncio.create_task(max_duration())
    try:
        await runner.run()
        end("agent_ended" if recorder.turns() else "client_left")
    except asyncio.CancelledError:
        # The runtime is shutting down (a deploy or scale-in): stop the pipeline and still
        # report everything measured so far instead of losing the call.
        end("shutdown")
        with contextlib.suppress(Exception):
            await runner.cancel()
    except Exception as exc:
        log.exception("session failed", extra={"session_id": session_id})
        recorder.errors.append(f"{type(exc).__name__}: {str(exc)[:200]}")
        end("error")
    finally:
        limiter.cancel()
        await resources.close()
    phrase = getattr(tts, "_phrase", None)  # set when the phrase cache wraps the TTS
    if phrase is not None:
        recorder.usage.tts_characters_cached = phrase.stats.characters_saved
        recorder.usage.tts_cache_hits = phrase.stats.hits
    recorder.usage.response_cache_hits = router.cache_hits
    recorder.usage.llm_turns_routed_small = router.routed_small
    return _report(
        agent, session_id, transport_kind, started_at, end_reason[0], recorder, recorder.errors
    )


def _report(
    agent: ResolvedAgent,
    session_id: str,
    transport_kind: Transport,
    started_at: datetime,
    reason: EndReason,
    recorder: TurnRecorder,
    errors: list[str],
) -> SessionReport:
    return SessionReport(
        session_id=session_id,
        agent_id=agent.agent_id,
        agent_version=agent.version,
        transport=transport_kind,
        started_at=started_at,
        ended_at=datetime.now(UTC),
        end_reason=reason,
        turns=recorder.turns(),
        usage=recorder.usage,
        external_providers=agent.external_providers(),
        errors=errors[:20],
    )


class _AnswerStore(BaseObserver):
    """Stores a turn's answer in the response cache once it played uninterrupted."""

    def __init__(self, recorder: TurnRecorder, router: TurnRouter) -> None:
        super().__init__()
        self._recorder = recorder
        self._router = router
        self._seen: set[int] = set()

    async def on_push_frame(self, data: FramePushed) -> None:
        frame: Frame = data.frame
        if not isinstance(frame, BotStoppedSpeakingFrame) or frame.id in self._seen:
            return
        self._seen.add(frame.id)
        turns = self._recorder.turns()
        if turns and not turns[-1].interrupted and turns[-1].agent_text:
            self._router.store_answer(turns[-1].agent_text)
