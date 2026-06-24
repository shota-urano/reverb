from __future__ import annotations

import logging
import time
import unicodedata
from typing import Optional, Protocol

from core.artifacts import TRANSLATION_PATH, read_transcript, write_translation
from core.errors import StageError
from core.progress_reporter import _EstimatedProgressReporter
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

        translated_by_id: dict[int, str] = {}
        non_empty_segments: list[TranscriptSegment] = []
        has_linguistic_segments = False
        for segment in transcript.segments:
            if not segment.text.strip():
                translated_by_id[segment.id] = ""
                continue
            non_empty_segments.append(segment)
            if is_non_linguistic(segment.text):
                translated_by_id[segment.id] = segment.text
            else:
                has_linguistic_segments = True

        chunks = list(_chunks(non_empty_segments, context.config.translate_chunk_size))
        if has_linguistic_segments:
            self._warm_up(context, model)

        last_chunk_seconds: Optional[float] = None
        for index, chunk in enumerate(chunks):
            base_progress = index / len(chunks)
            ceiling_progress = (index + 1) / len(chunks)
            reporter = _EstimatedProgressReporter(
                progress_cb=context.report_progress,
                estimated_total_seconds=(
                    last_chunk_seconds
                    if last_chunk_seconds is not None
                    else context.config.translate_progress_estimated_chunk_seconds
                ),
                base_progress=base_progress,
                ceiling_progress=ceiling_progress,
                interval_seconds=context.config.translate_progress_interval_seconds,
                thread_name="translate-progress",
            )
            reporter.start()
            started_at = time.monotonic()
            try:
                if any(not is_non_linguistic(segment.text) for segment in chunk):
                    translated = self._translate_chunk(
                        context, transcript.segments, chunk, transcript.language, model
                    )
                    for segment, target in zip(chunk, translated):
                        translated_by_id[segment.id] = target
            finally:
                reporter.stop()
            last_chunk_seconds = time.monotonic() - started_at
            context.report_progress(ceiling_progress)

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
        target_segments = [segment for segment in chunk if not is_non_linguistic(segment.text)]
        if not target_segments:
            return [segment.text for segment in chunk]

        request_segments = _context_segments(
            all_segments,
            chunk[0],
            context.config.translate_context_window,
        ) + [
            _segment_payload(segment, context_only=is_non_linguistic(segment.text))
            for segment in chunk
        ]

        attempts = context.config.translate_max_retries + 1
        last_error: Optional[StageError] = None
        last_translated: Optional[list[str]] = None
        for attempt in range(attempts):
            try:
                translated = self.adapter.translate(
                    request_segments,
                    model,
                    source_lang,
                    context.config.translate_system_prompt,
                    context.config.translate_context_window,
                )
                shape_error = _translation_shape_error(target_segments, translated)
                if shape_error is None and not _empty_translation_indexes(
                    target_segments,
                    translated,
                ):
                    return _merge_chunk_targets(chunk, target_segments, translated)
                if shape_error is None:
                    last_translated = translated
                    last_error = StageError(
                        "TRANSLATE_INCOMPLETE",
                        "Translation returned an empty target for a non-empty source segment.",
                        retryable=True,
                    )
                    if attempt == attempts - 1:
                        return _fallback_empty_translations(
                            context, chunk, target_segments, translated
                        )
                else:
                    last_error = shape_error
            except StageError as exc:
                if not exc.retryable:
                    raise
                last_error = exc
            if attempt < attempts - 1:
                _sleep_before_retry(context.config.translate_retry_initial_wait, attempt)
        if last_error is not None:
            if last_error.code == "TRANSLATE_INCOMPLETE" and last_translated is not None:
                return _fallback_empty_translations(
                    context,
                    chunk,
                    target_segments,
                    last_translated,
                )
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


def is_non_linguistic(text: str) -> bool:
    return not any(_is_linguistic_character(char) for char in text)


def _is_linguistic_character(char: str) -> bool:
    return unicodedata.category(char).startswith("L") or _is_cjk_character(char)


def _is_cjk_character(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2A6DF
        or 0x2A700 <= codepoint <= 0x2B73F
        or 0x2B740 <= codepoint <= 0x2B81F
        or 0x2B820 <= codepoint <= 0x2CEAF
        or 0x2CEB0 <= codepoint <= 0x2EBEF
        or 0x30000 <= codepoint <= 0x3134F
    )


def _translation_shape_error(
    chunk: list[TranscriptSegment],
    translated: list[str],
) -> Optional[StageError]:
    if len(translated) != len(chunk):
        return StageError(
            "TRANSLATE_MISALIGN",
            "Translated segment count did not match input segment count.",
            retryable=True,
        )
    return None


def _empty_translation_indexes(
    target_segments: list[TranscriptSegment],
    translated: list[str],
) -> list[int]:
    return [
        index
        for index, (segment, target) in enumerate(zip(target_segments, translated))
        if segment.text.strip() and not target.strip()
    ]


def _fallback_empty_translations(
    context: PipelineContext,
    chunk: list[TranscriptSegment],
    target_segments: list[TranscriptSegment],
    translated: list[str],
) -> list[str]:
    empty_indexes = _empty_translation_indexes(target_segments, translated)
    fallback_count = len(empty_indexes)
    target_count = len(target_segments)
    fallback_fraction = fallback_count / target_count if target_count else 0.0
    if fallback_count > 1 and fallback_fraction > context.config.translate_fallback_threshold:
        raise StageError(
            "TRANSLATE_INCOMPLETE",
            "Translation returned empty targets for too many source segments.",
            retryable=True,
        )

    logger.warning(
        "Translation returned empty targets after retries; using source text for %d segment(s).",
        fallback_count,
    )
    fallback_by_id = {target_segments[index].id for index in empty_indexes}
    recovered = [
        segment.text if segment.id in fallback_by_id else target
        for segment, target in zip(target_segments, translated)
    ]
    return _merge_chunk_targets(chunk, target_segments, recovered)


def _merge_chunk_targets(
    chunk: list[TranscriptSegment],
    target_segments: list[TranscriptSegment],
    translated: list[str],
) -> list[str]:
    translated_by_id = {segment.id: target for segment, target in zip(target_segments, translated)}
    return [
        segment.text if is_non_linguistic(segment.text) else translated_by_id[segment.id]
        for segment in chunk
    ]


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
