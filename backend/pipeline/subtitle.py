from __future__ import annotations

import logging
from dataclasses import dataclass

from core.artifacts import SUBTITLES_PATH, read_translation, write_subtitles
from core.config import BackendConfig
from pipeline.stage import PipelineContext, Stage
from schemas.artifacts import SubtitleCue, Subtitles, TranslationSegment
from schemas.enums import StageName

logger = logging.getLogger(__name__)

_BREAK_PUNCTUATION = "、。！？!?；;：:"
_SOFT_BOUNDARY_SUFFIXES = (
    "ので",
    "から",
    "ため",
    "なら",
    "また",
    "まず",
    "次に",
    "そして",
    "しかし",
    "一方",
    "つまり",
)
_LINE_BREAK_AFTER = (
    "は",
    "が",
    "を",
    "に",
    "で",
    "と",
    "へ",
    "も",
    "や",
    "の",
    "て",
    "し",
    "、",
)


@dataclass
class _DraftCue:
    start: float
    end: float
    text: str
    segment_ids: list[int]


class SubtitleStage(Stage):
    name = StageName.subtitle

    def run(self, context: PipelineContext) -> str:
        context.report_progress(0.0)
        translation = read_translation(context.project_dir)

        if all(not segment.target.strip() for segment in translation.segments):
            write_subtitles(context.project_dir, Subtitles(cues=[]))
            context.report_progress(1.0)
            return str(SUBTITLES_PATH)

        context.report_progress(0.25)
        segments = translation.segments
        sorted_segments = sorted(segments, key=lambda segment: (segment.start, segment.id))
        if [(segment.start, segment.id) for segment in segments] != [
            (segment.start, segment.id) for segment in sorted_segments
        ]:
            logger.warning(
                "Translation segments are not sorted by start time; "
                "sorting before subtitle cue generation."
            )
        drafts = _build_draft_cues(sorted_segments, context.config)
        _adjust_short_cues(drafts, context.config)
        cues = _finalize_cues(drafts, context.config)
        context.report_progress(0.85)

        write_subtitles(context.project_dir, Subtitles(cues=cues))
        context.report_progress(1.0)
        return str(SUBTITLES_PATH)


def _build_draft_cues(
    segments: list[TranslationSegment],
    config: BackendConfig,
) -> list[_DraftCue]:
    cues: list[_DraftCue] = []
    capacity = _cue_capacity(config)
    for segment in segments:
        text = _normalize_text(segment.target)
        if not text:
            continue
        chunks = _split_for_cues(text, capacity)
        total_chars = sum(len(chunk) for chunk in chunks)
        if total_chars <= 0:
            continue
        segment_duration = max(0.0, segment.end - segment.start)
        cursor = segment.start
        for index, chunk in enumerate(chunks):
            if index == len(chunks) - 1:
                end = segment.end
            else:
                ratio = len(chunk) / total_chars
                end = cursor + segment_duration * ratio
            cues.append(
                _DraftCue(
                    start=cursor,
                    end=max(cursor, end),
                    text=chunk,
                    segment_ids=[segment.id],
                )
            )
            cursor = max(cursor, end)
    return cues


def _split_for_cues(text: str, capacity: int) -> list[str]:
    if len(text) <= capacity:
        return [text]

    units = _semantic_units(text)
    chunks = _pack_units(units, capacity)
    result: list[str] = []
    for chunk in chunks:
        if len(chunk) <= capacity:
            result.append(chunk)
            continue
        logger.warning("Subtitle cue text exceeds configured capacity; splitting best-effort.")
        result.extend(_split_long_text(chunk, capacity))
    return [chunk for chunk in result if chunk]


def _adjust_short_cues(cues: list[_DraftCue], config: BackendConfig) -> None:
    min_duration = config.subtitle_min_duration_seconds
    index = 0
    while index < len(cues):
        cue = cues[index]
        if cue.end - cue.start >= min_duration:
            index += 1
            continue

        desired_end = cue.start + min_duration
        next_start = cues[index + 1].start if index + 1 < len(cues) else None
        if next_start is None or desired_end <= next_start:
            cue.end = desired_end
            index += 1
            continue

        if index + 1 < len(cues):
            following = cues.pop(index + 1)
            cue.end = max(cue.end, following.end)
            cue.text = _join_text(cue.text, following.text)
            cue.segment_ids = _merge_segment_ids(cue.segment_ids, following.segment_ids)
            if _text_exceeds_capacity(cue.text, config):
                logger.warning("Merged subtitle cue exceeds configured text capacity.")
            continue

        logger.warning(
            "Subtitle cue cannot reach minimum duration without overlap; extending tail."
        )
        cue.end = desired_end
        index += 1


def _finalize_cues(
    drafts: list[_DraftCue],
    config: BackendConfig,
) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    previous_end = 0.0
    for cue_id, draft in enumerate(drafts):
        start = max(draft.start, previous_end)
        end = max(start, draft.end)
        if end == start and draft.text:
            logger.warning("Subtitle cue has zero duration after timing adjustment.")
        lines = _wrap_lines(draft.text, config)
        cues.append(
            SubtitleCue(
                id=cue_id,
                start=start,
                end=end,
                lines=lines,
                segmentIds=draft.segment_ids,
            )
        )
        previous_end = end
    return cues


def _wrap_lines(text: str, config: BackendConfig) -> list[str]:
    target = config.subtitle_target_full_width_chars
    max_lines = config.subtitle_max_lines
    if len(text) <= target or max_lines <= 1:
        if len(text) > target and max_lines <= 1:
            logger.warning("Subtitle line exceeds configured length; max lines is one.")
        return [text]

    units = _semantic_units(text)
    lines = _pack_units(units, target)
    expanded: list[str] = []
    for line in lines:
        if len(line) <= target:
            expanded.append(line)
        else:
            logger.warning("Subtitle line exceeds configured length; splitting best-effort.")
            expanded.extend(_split_long_text(line, target))

    if len(expanded) <= max_lines:
        return expanded

    head = expanded[: max_lines - 1]
    tail = "".join(expanded[max_lines - 1 :])
    if len(tail) > target:
        logger.warning("Subtitle cue exceeds configured max lines; preserving best-effort tail.")
    return head + [tail]


def _semantic_units(text: str) -> list[str]:
    units: list[str] = []
    current = ""
    for char in text:
        current += char
        if char in _BREAK_PUNCTUATION or char.isspace() or _ends_with_soft_boundary(current):
            units.append(current.strip())
            current = ""
    if current.strip():
        units.append(current.strip())
    return [unit for unit in units if unit]


def _pack_units(units: list[str], limit: int) -> list[str]:
    packed: list[str] = []
    current = ""
    for unit in units:
        candidate = _join_text(current, unit) if current else unit
        if current and len(candidate) > limit:
            packed.append(current)
            current = unit
        else:
            current = candidate
    if current:
        packed.append(current)
    return packed


def _split_long_text(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = _best_split_index(remaining, limit)
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        chunks.append(remaining)
    return chunks


def _best_split_index(text: str, limit: int) -> int:
    boundary = -1
    for index in range(1, min(limit, len(text)) + 1):
        if text[index - 1] in _LINE_BREAK_AFTER:
            boundary = index
    if boundary > 0:
        return boundary
    logger.warning("Subtitle text has no semantic boundary near target length; splitting hard.")
    return min(limit, len(text))


def _normalize_text(text: str) -> str:
    return "".join(text.split())


def _ends_with_soft_boundary(text: str) -> bool:
    return any(text.endswith(suffix) for suffix in _SOFT_BOUNDARY_SUFFIXES)


def _join_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    return f"{left}{right}"


def _merge_segment_ids(left: list[int], right: list[int]) -> list[int]:
    merged: list[int] = []
    for segment_id in left + right:
        if segment_id not in merged:
            merged.append(segment_id)
    return merged


def _text_exceeds_capacity(text: str, config: BackendConfig) -> bool:
    return len(text) > _cue_capacity(config)


def _cue_capacity(config: BackendConfig) -> int:
    return config.subtitle_target_full_width_chars * config.subtitle_max_lines
