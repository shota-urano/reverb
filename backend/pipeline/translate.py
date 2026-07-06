from __future__ import annotations

import logging
import time
import unicodedata
from difflib import SequenceMatcher
from typing import Optional, Protocol, TypeVar, Union

from core.artifacts import (
    GLOSSARY_PATH,
    TRANSLATION_PATH,
    read_glossary,
    read_transcript,
    write_glossary,
    write_translation,
    write_translation_raw,
)
from core.errors import StageError
from core.progress_reporter import _EstimatedProgressReporter
from pipeline.stage import PipelineContext, Stage
from schemas.artifacts import (
    Glossary,
    GlossaryEntry,
    Translation,
    TranslationSegment,
    TranscriptSegment,
)
from schemas.enums import StageName

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Translator(Protocol):
    def generate_glossary(
        self,
        transcript: str,
        model: str,
        source_lang: Optional[str],
        max_terms: int,
    ) -> list[dict[str, str]]: ...

    def warm_up(self, model: str, system_prompt: str) -> None: ...

    def translate(
        self,
        segments: list[dict[str, object]],
        model: str,
        source_lang: Optional[str],
        system_prompt: str,
        context_window: int,
        glossary: list[dict[str, str]],
    ) -> list[str]: ...

    def polish(
        self,
        segments: list[dict],
        model: str,
        system_prompt: str,
        temperature: float,
    ) -> list[str]: ...


class TranslateStage(Stage):
    name = StageName.translate

    def __init__(self, adapter: Translator) -> None:
        self.adapter = adapter

    def run(self, context: PipelineContext) -> str:
        context.report_progress(0.0)
        transcript = read_transcript(context.project_dir)
        model = context.job.settings.translate.model or context.config.default_translate_model
        glossary = self._load_or_generate_glossary(context, transcript, model)
        segment_groups = group_segments_by_sentence(
            transcript.segments,
            target_seconds=context.config.translate_group_target_seconds,
            gap_seconds=context.config.translate_group_gap_seconds,
        )
        segment_groups = dedup_adjacent_groups(
            segment_groups,
            context.config.translate_dedup_similarity,
            context.config.translate_dedup_enabled,
        )

        chunks = list(_chunks(segment_groups, context.config.translate_chunk_size))
        if any(_is_translatable_group(group) for group in segment_groups):
            self._warm_up(context, model)

        translation_segments: list[TranslationSegment] = []
        translatable_count: int = 0
        fallback_count: int = 0
        last_chunk_seconds: Optional[float] = None
        processed_group_count = 0
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
                for request_groups in _chunks(chunk, context.config.translate_chunk_groups):
                    following_group_index = processed_group_count + len(request_groups)
                    following_group = (
                        segment_groups[following_group_index]
                        if following_group_index < len(segment_groups)
                        else None
                    )
                    translated_groups = self._translate_groups(
                        context,
                        request_groups,
                        translation_segments,
                        transcript.language,
                        model,
                        glossary,
                        following_group=following_group,
                    )
                    for group, (target, fell_back) in zip(
                        request_groups,
                        translated_groups,
                    ):
                        if _is_translatable_group(group):
                            translatable_count += 1
                            if fell_back:
                                fallback_count += 1
                        translation_segments.append(
                            TranslationSegment(
                                id=group[0].id,
                                start=group[0].start,
                                end=group[-1].end,
                                source=_group_source(group),
                                target=target,
                            )
                        )
                    processed_group_count += len(request_groups)
            finally:
                reporter.stop()
            last_chunk_seconds = time.monotonic() - started_at
            context.report_progress(ceiling_progress)

        if (
            fallback_count > 1
            and translatable_count > 0
            and fallback_count / translatable_count > context.config.translate_fallback_threshold
        ):
            raise StageError(
                "TRANSLATE_INCOMPLETE",
                "Translation returned empty targets for too many source segments.",
                retryable=True,
            )
        if not segment_groups:
            context.report_progress(1.0)
        translation = Translation(
            model=model,
            sourceLanguage=transcript.language,
            targetLanguage="ja",
            segments=translation_segments,
        )
        if context.config.translate_polish_enabled:
            write_translation_raw(context.project_dir, translation)
            self._polish_translation(context, translation)
        write_translation(context.project_dir, translation)
        return str(TRANSLATION_PATH)

    def _polish_translation(
        self,
        context: PipelineContext,
        translation: Translation,
    ) -> None:
        started_at = time.monotonic()
        model = context.config.translate_polish_model or context.config.default_translate_model
        target_chars_by_id = {
            segment.id: _target_chars(
                segment,
                context.config.translate_chars_per_sec,
                trailing_gap_seconds=_trailing_gap_seconds(
                    segment.end,
                    (
                        translation.segments[index + 1].start
                        if index + 1 < len(translation.segments)
                        else None
                    ),
                ),
                gap_cap_seconds=context.config.translate_target_gap_cap_seconds,
                speed_factor=context.config.translate_target_speed_factor,
            )
            for index, segment in enumerate(translation.segments)
        }
        confirmed_polished_segments: list[TranslationSegment] = []
        for chunk in _chunks(translation.segments, context.config.translate_chunk_size):
            input_segments = [segment for segment in chunk if segment.target]
            inputs = _confirmed_polish_context_segments(
                confirmed_polished_segments,
                context.config.translate_polish_context_window,
                target_chars_by_id,
            ) + [
                {
                    "id": segment.id,
                    "text": segment.target,
                    "targetChars": target_chars_by_id[segment.id],
                }
                for segment in input_segments
            ]
            if not input_segments:
                continue
            try:
                polished = self.adapter.polish(
                    inputs,
                    model,
                    context.config.translate_polish_system_prompt,
                    context.config.translate_polish_temperature,
                )
                if len(polished) != len(input_segments):
                    raise ValueError("Polished segment count did not match input segment count.")
                resolved_targets = [
                    polished_text if polished_text.strip() else segment.target
                    for segment, polished_text in zip(input_segments, polished)
                ]
            except Exception:
                logger.warning(
                    "Japanese polish failed; using pre-polish targets for this chunk.",
                    exc_info=True,
                )
                continue

            for segment, resolved_target in zip(input_segments, resolved_targets):
                segment.target = resolved_target
            confirmed_polished_segments.extend(input_segments)
        logger.info(
            "Japanese polish completed in %.3f seconds.",
            time.monotonic() - started_at,
        )

    def _translate_groups(
        self,
        context: PipelineContext,
        groups: list[list[TranscriptSegment]],
        confirmed_segments: list[TranslationSegment],
        source_lang: Optional[str],
        model: str,
        glossary: list[dict[str, str]],
        *,
        following_group: Optional[list[TranscriptSegment]] = None,
    ) -> list[tuple[str, bool]]:
        translatable_groups = [group for group in groups if _is_translatable_group(group)]
        if not translatable_groups:
            return [(_passthrough_target(group), False) for group in groups]

        input_groups = [
            (group, groups[index + 1] if index + 1 < len(groups) else following_group)
            for index, group in enumerate(groups)
            if _is_translatable_group(group)
        ]
        request_segments = _confirmed_context_segments(
            confirmed_segments,
            context.config.translate_context_window,
        ) + [
            _group_payload(
                group,
                context_only=False,
                target_chars=_target_chars(
                    group,
                    context.config.translate_chars_per_sec,
                    trailing_gap_seconds=_trailing_gap_seconds(
                        group[-1].end,
                        next_group[0].start if next_group is not None else None,
                    ),
                    gap_cap_seconds=context.config.translate_target_gap_cap_seconds,
                    speed_factor=context.config.translate_target_speed_factor,
                ),
            )
            for group, next_group in input_groups
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
                    glossary,
                )
                shape_error = _translation_group_shape_error(translatable_groups, translated)
                if shape_error is None and not _empty_group_translation_indexes(
                    translatable_groups,
                    translated,
                ):
                    return _merge_group_targets(groups, translatable_groups, translated)
                if shape_error is None:
                    last_translated = translated
                    last_error = StageError(
                        "TRANSLATE_INCOMPLETE",
                        "Translation returned an empty target for a non-empty source segment.",
                        retryable=True,
                    )
                    if attempt == attempts - 1:
                        return _fallback_empty_group_translations(
                            groups,
                            translatable_groups,
                            translated,
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
                return _fallback_empty_group_translations(
                    groups,
                    translatable_groups,
                    last_translated,
                )
            raise last_error
        raise StageError(
            "TRANSLATE_MISALIGN",
            "Translated segment count did not match input segment count.",
            retryable=True,
        )

    def _translate_chunk(
        self,
        context: PipelineContext,
        all_segments: list[TranscriptSegment],
        chunk: list[TranscriptSegment],
        source_lang: Optional[str],
        model: str,
        glossary: Optional[list[dict[str, str]]] = None,
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
                    glossary or [],
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

    def _load_or_generate_glossary(
        self,
        context: PipelineContext,
        transcript,
        model: str,
    ) -> list[dict[str, str]]:
        if not context.config.translate_glossary_enabled:
            return []
        try:
            if (context.project_dir / GLOSSARY_PATH).exists():
                glossary = read_glossary(context.project_dir)
            else:
                entries = self.adapter.generate_glossary(
                    "\n".join(segment.text for segment in transcript.segments),
                    model,
                    transcript.language,
                    context.config.translate_glossary_max_terms,
                )
                glossary = Glossary(entries=[GlossaryEntry(**entry) for entry in entries])
                write_glossary(context.project_dir, glossary)
            return [entry.model_dump() for entry in glossary.entries]
        except Exception:
            logger.warning(
                "Glossary generation failed; continuing without glossary.",
                exc_info=True,
            )
            return []


def _sleep_before_retry(initial_wait: float, attempt: int) -> None:
    wait_seconds = initial_wait * (2**attempt)
    if wait_seconds > 0:
        time.sleep(wait_seconds)


def group_segments_by_sentence(
    segments: list[TranscriptSegment],
    target_seconds: Optional[float] = None,
    gap_seconds: float = 1.0,
) -> list[list[TranscriptSegment]]:
    groups: list[list[TranscriptSegment]] = []
    current: list[TranscriptSegment] = []

    for index, segment in enumerate(segments):
        source = segment.text
        if not source.strip() or is_non_linguistic(source):
            if current:
                groups.append(current)
                current = []
            groups.append([segment])
            continue

        current.append(segment)
        if _ends_with_sentence_terminal(source):
            next_segment = segments[index + 1] if index + 1 < len(segments) else None
            closes_group = target_seconds is None or next_segment is None
            if next_segment is not None and target_seconds is not None:
                gap = next_segment.start - segment.end
                duration_with_next = next_segment.end - current[0].start
                closes_group = gap >= gap_seconds or duration_with_next > target_seconds
            if closes_group:
                groups.append(current)
                current = []

    if current:
        groups.append(current)
    return groups


class _DedupMergedGroup(list[TranscriptSegment]):
    def __init__(
        self,
        segments: list[TranscriptSegment],
        representative_segment_count: int,
    ) -> None:
        super().__init__(segments)
        self.representative_segment_count = representative_segment_count


def dedup_adjacent_groups(
    groups: list[list[TranscriptSegment]],
    similarity_threshold: float,
    enabled: bool,
) -> list[list[TranscriptSegment]]:
    if not enabled:
        return groups

    deduplicated: list[list[TranscriptSegment]] = []
    previous_group: Optional[list[TranscriptSegment]] = None
    for group in groups:
        if previous_group is not None and _groups_are_similar(
            previous_group,
            group,
            similarity_threshold,
        ):
            prior = deduplicated[-1]
            representative_count = (
                prior.representative_segment_count
                if isinstance(prior, _DedupMergedGroup)
                else len(prior)
            )
            deduplicated[-1] = _DedupMergedGroup(
                [*prior, *group],
                representative_count,
            )
        else:
            deduplicated.append(group)
        previous_group = group
    return deduplicated


def _groups_are_similar(
    first: list[TranscriptSegment],
    second: list[TranscriptSegment],
    similarity_threshold: float,
) -> bool:
    if not first or not second:
        return False
    first_source = _group_source(first)
    second_source = _group_source(second)
    if (
        not first_source.strip()
        or not second_source.strip()
        or is_non_linguistic(first_source)
        or is_non_linguistic(second_source)
    ):
        return False
    first_normalized = _normalize_dedup_source(first_source)
    second_normalized = _normalize_dedup_source(second_source)
    if not first_normalized or not second_normalized:
        return False
    return (
        SequenceMatcher(None, first_normalized, second_normalized).ratio() >= similarity_threshold
    )


def _normalize_dedup_source(source: str) -> str:
    without_symbols = "".join(
        char.lower() for char in source if unicodedata.category(char)[0] not in {"P", "S"}
    )
    return " ".join(without_symbols.split())


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


def _translation_group_shape_error(
    groups: list[list[TranscriptSegment]],
    translated: list[str],
) -> Optional[StageError]:
    if len(translated) != len(groups):
        return StageError(
            "TRANSLATE_MISALIGN",
            "Translated segment count did not match input segment count.",
            retryable=True,
        )
    return None


def _empty_group_translation_indexes(
    groups: list[list[TranscriptSegment]],
    translated: list[str],
) -> list[int]:
    return [
        index
        for index, (group, target) in enumerate(zip(groups, translated))
        if _group_source(group).strip() and not target.strip()
    ]


def _fallback_empty_group_translations(
    groups: list[list[TranscriptSegment]],
    translatable_groups: list[list[TranscriptSegment]],
    translated: list[str],
) -> list[tuple[str, bool]]:
    empty_indexes = _empty_group_translation_indexes(translatable_groups, translated)
    logger.warning(
        "Translation returned empty targets after retries; using source text for %d segment(s).",
        len(empty_indexes),
    )
    fallback_ids = {translatable_groups[index][0].id for index in empty_indexes}
    recovered = [
        _group_source(group) if group[0].id in fallback_ids else target
        for group, target in zip(translatable_groups, translated)
    ]
    return _merge_group_targets(
        groups,
        translatable_groups,
        recovered,
        fallback_ids=fallback_ids,
    )


def _merge_group_targets(
    groups: list[list[TranscriptSegment]],
    translatable_groups: list[list[TranscriptSegment]],
    translated: list[str],
    *,
    fallback_ids: Optional[set[int]] = None,
) -> list[tuple[str, bool]]:
    targets_by_id = {group[0].id: target for group, target in zip(translatable_groups, translated)}
    fallback_ids = fallback_ids or set()
    return [
        (
            (
                targets_by_id[group[0].id]
                if group[0].id in targets_by_id
                else _passthrough_target(group)
            ),
            group[0].id in fallback_ids,
        )
        for group in groups
    ]


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


def _is_translatable_group(group: list[TranscriptSegment]) -> bool:
    source = _group_source(group)
    return bool(source.strip()) and not is_non_linguistic(source)


def _group_source(group: list[TranscriptSegment]) -> str:
    source_segments = (
        group[: group.representative_segment_count]
        if isinstance(group, _DedupMergedGroup)
        else group
    )
    if len(source_segments) == 1:
        return source_segments[0].text
    return " ".join(segment.text.strip() for segment in source_segments if segment.text.strip())


def _passthrough_target(group: list[TranscriptSegment]) -> str:
    source = _group_source(group)
    return source if source.strip() else ""


def _target_chars(
    segment_or_group: Union[list[TranscriptSegment], TranslationSegment],
    chars_per_second: float,
    *,
    trailing_gap_seconds: float = 0.0,
    gap_cap_seconds: float = 0.0,
    speed_factor: float = 1.0,
) -> int:
    if isinstance(segment_or_group, list):
        start = segment_or_group[0].start
        end = segment_or_group[-1].end
    else:
        start = segment_or_group.start
        end = segment_or_group.end
    duration = max(0.0, end - start)
    usable_gap = min(max(0.0, trailing_gap_seconds), max(0.0, gap_cap_seconds))
    effective_speed_factor = 1.0 if speed_factor == 0 else speed_factor
    # 0秒枠（Whisper出力で起こり得る）で targetChars: 0 を渡すと素直なモデルが
    # 空文字を返しリトライを浪費するため、下限を設ける。
    return max(
        1,
        int(round((duration + usable_gap) * chars_per_second * effective_speed_factor)),
    )


def _trailing_gap_seconds(current_end: float, next_start: Optional[float]) -> float:
    if next_start is None:
        return 0.0
    return max(0.0, next_start - current_end)


def _ends_with_sentence_terminal(text: str) -> bool:
    stripped = text.rstrip()
    while stripped and stripped[-1] in _SENTENCE_TRAILING_QUOTES:
        stripped = stripped[:-1].rstrip()
    return bool(stripped) and stripped[-1] in _SENTENCE_TERMINALS


_SENTENCE_TERMINALS = frozenset(".?!。！？")
_SENTENCE_TRAILING_QUOTES = frozenset("\"'”’»」』）)]}】")


def _chunks(segments: list[T], chunk_size: int) -> list[list[T]]:
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


def _confirmed_context_segments(
    confirmed_segments: list[TranslationSegment],
    context_window: int,
) -> list[dict[str, object]]:
    if context_window <= 0:
        return []
    prior = [segment for segment in confirmed_segments if segment.source.strip()]
    return [
        {
            "id": segment.id,
            "start": segment.start,
            "end": segment.end,
            "text": segment.source,
            "target": segment.target,
            "contextOnly": True,
        }
        for segment in prior[-max(0, context_window) :]
    ]


def _confirmed_polish_context_segments(
    confirmed_segments: list[TranslationSegment],
    context_window: int,
    target_chars_by_id: dict[int, int],
) -> list[dict[str, object]]:
    if context_window <= 0:
        return []
    prior = [segment for segment in confirmed_segments if segment.source.strip()]
    return [
        {
            "id": segment.id,
            "text": segment.source,
            "target": segment.target,
            "targetChars": target_chars_by_id[segment.id],
            "contextOnly": True,
        }
        for segment in prior[-context_window:]
    ]


def _segment_payload(segment: TranscriptSegment, *, context_only: bool) -> dict[str, object]:
    return {
        "id": segment.id,
        "start": segment.start,
        "end": segment.end,
        "text": segment.text,
        "contextOnly": context_only,
    }


def _group_payload(
    group: list[TranscriptSegment],
    *,
    context_only: bool,
    target_chars: Optional[int] = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": group[0].id,
        "start": group[0].start,
        "end": group[-1].end,
        "text": _group_source(group),
        "contextOnly": context_only,
    }
    if target_chars is not None:
        payload["targetChars"] = target_chars
    return payload
