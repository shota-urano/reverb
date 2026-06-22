from __future__ import annotations

import logging
import time
from typing import Optional, Protocol

from core.artifacts import TRANSLATION_PATH, read_transcript, write_translation
from core.errors import StageError
from pipeline.stage import PipelineContext, Stage
from schemas.artifacts import Translation, TranslationSegment, TranscriptSegment
from schemas.enums import StageName

logger = logging.getLogger(__name__)


class Translator(Protocol):
    def warm_up(self, model: str, system_prompt: str) -> None: ...

    def translate(
        self,
        segments: list[dict[str, object]],
        model: str,
        source_lang: Optional[str],
        system_prompt: str,
        context_window: int,
    ) -> list[str]: ...


class TranslateStage(Stage):
    name = StageName.translate

    def __init__(self, adapter: Translator) -> None:
        self.adapter = adapter

    def run(self, context: PipelineContext) -> str:
        context.report_progress(0.0)
        transcript = read_transcript(context.project_dir)
        model = context.job.settings.translate.model or context.config.default_translate_model

        if all(not segment.text.strip() for segment in transcript.segments):
            write_translation(
                context.project_dir,
                Translation(
                    model=model,
                    sourceLanguage=transcript.language,
                    targetLanguage="ja",
                    segments=[],
                ),
            )
            context.report_progress(1.0)
            return str(TRANSLATION_PATH)

        translated_by_id: dict[int, str] = {
            segment.id: "" for segment in transcript.segments if not segment.text.strip()
        }
        translatable_segments = [segment for segment in transcript.segments if segment.text.strip()]
        chunks = list(_chunks(translatable_segments, context.config.translate_chunk_size))
        self._warm_up(context, model)

        for index, chunk in enumerate(chunks):
            translated = self._translate_chunk(
                context, transcript.segments, chunk, transcript.language, model
            )
            for segment, target in zip(chunk, translated):
                translated_by_id[segment.id] = target
            context.report_progress((index + 1) / len(chunks))

        translation_segments = [
            TranslationSegment(
                id=segment.id,
                start=segment.start,
                end=segment.end,
                source=segment.text,
                target=translated_by_id[segment.id],
            )
            for segment in transcript.segments
        ]
        write_translation(
            context.project_dir,
            Translation(
                model=model,
                sourceLanguage=transcript.language,
                targetLanguage="ja",
                segments=translation_segments,
            ),
        )
        return str(TRANSLATION_PATH)

    def _translate_chunk(
        self,
        context: PipelineContext,
        all_segments: list[TranscriptSegment],
        chunk: list[TranscriptSegment],
        source_lang: Optional[str],
        model: str,
    ) -> list[str]:
        request_segments = _context_segments(
            all_segments,
            chunk[0],
            context.config.translate_context_window,
        ) + [_segment_payload(segment, context_only=False) for segment in chunk]

        attempts = context.config.translate_max_retries + 1
        last_error: Optional[StageError] = None
        for attempt in range(attempts):
            try:
                translated = self.adapter.translate(
                    request_segments,
                    model,
                    source_lang,
                    context.config.translate_system_prompt,
                    context.config.translate_context_window,
                )
                if len(translated) == len(chunk):
                    return translated
                last_error = StageError(
                    "TRANSLATE_MISALIGN",
                    "Translated segment count did not match input segment count.",
                    retryable=True,
                )
            except StageError as exc:
                if not exc.retryable:
                    raise
                last_error = exc
            if attempt < attempts - 1:
                _sleep_before_retry(context.config.translate_retry_initial_wait, attempt)
        if last_error is not None:
            raise last_error
        raise StageError(
            "TRANSLATE_MISALIGN",
            "Translated segment count did not match input segment count.",
            retryable=True,
        )

    def _warm_up(self, context: PipelineContext, model: str) -> None:
        try:
            self.adapter.warm_up(model, context.config.translate_system_prompt)
        except Exception:
            logger.warning(
                "Ollama warm-up failed; continuing with translate stage.",
                exc_info=True,
            )


def _sleep_before_retry(initial_wait: float, attempt: int) -> None:
    wait_seconds = initial_wait * (2**attempt)
    if wait_seconds > 0:
        time.sleep(wait_seconds)


def _chunks(segments: list[TranscriptSegment], chunk_size: int) -> list[list[TranscriptSegment]]:
    size = max(1, chunk_size)
    return [segments[index : index + size] for index in range(0, len(segments), size)]


def _context_segments(
    all_segments: list[TranscriptSegment],
    first_chunk_segment: TranscriptSegment,
    context_window: int,
) -> list[dict[str, object]]:
    prior = [segment for segment in all_segments if segment.id < first_chunk_segment.id]
    return [
        _segment_payload(segment, context_only=True)
        for segment in prior[-max(0, context_window) :]
        if segment.text.strip()
    ]


def _segment_payload(segment: TranscriptSegment, *, context_only: bool) -> dict[str, object]:
    return {
        "id": segment.id,
        "start": segment.start,
        "end": segment.end,
        "text": segment.text,
        "contextOnly": context_only,
    }
