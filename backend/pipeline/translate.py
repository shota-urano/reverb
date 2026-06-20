from __future__ import annotations

from typing import Optional, Protocol

from core.artifacts import TRANSLATION_PATH, read_transcript, write_translation
from core.errors import StageError
from pipeline.stage import PipelineContext, Stage
from schemas.artifacts import Translation, TranslationSegment, TranscriptSegment
from schemas.enums import StageName


class Translator(Protocol):
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

        for index, chunk in enumerate(chunks):
            translated = self._translate_chunk(
                context, transcript.segments, chunk, transcript.language
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
    ) -> list[str]:
        request_segments = _context_segments(
            all_segments,
            chunk[0],
            context.config.translate_context_window,
        ) + [_segment_payload(segment, context_only=False) for segment in chunk]

        for attempt in range(2):
            translated = self.adapter.translate(
                request_segments,
                context.job.settings.translate.model or context.config.default_translate_model,
                source_lang,
                context.config.translate_system_prompt,
                context.config.translate_context_window,
            )
            if len(translated) == len(chunk):
                return translated
            if attempt == 0:
                continue
            raise StageError(
                "TRANSLATE_MISALIGN",
                "Translated segment count did not match input segment count.",
                retryable=True,
            )


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
