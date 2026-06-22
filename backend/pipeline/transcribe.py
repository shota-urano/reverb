from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol

from core.artifacts import AUDIO_PATH, TRANSCRIPT_PATH, write_transcript
from pipeline.stage import PipelineContext, Stage
from schemas.artifacts import Transcript, TranscriptSegment
from schemas.enums import StageName

logger = logging.getLogger(__name__)


_LATIN_DOMINANCE_THRESHOLD = 0.5
_CJK_RANGES = (
    (0x3040, 0x309F),
    (0x30A0, 0x30FF),
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
    (0x20000, 0x2A6DF),
)


class Transcriber(Protocol):
    def transcribe(
        self,
        audio_path: Path,
        model: str,
        language: Optional[str],
        options: Dict[str, object],
        progress_cb: Callable[[float], None],
    ) -> tuple[Optional[str], list[dict]]: ...


class TranscribeStage(Stage):
    name = StageName.transcribe

    def __init__(self, adapter: Transcriber) -> None:
        self.adapter = adapter

    def run(self, context: PipelineContext) -> str:
        audio_path = context.project_dir / AUDIO_PATH
        model = context.job.settings.stt.model or context.config.default_stt_model
        language = context.job.settings.stt.language
        engine = context.config.default_stt_engine

        language_detected, raw_segments = self.adapter.transcribe(
            audio_path,
            model,
            language,
            {
                "duration": context.job.duration,
                "engine": engine,
            },
            context.report_progress,
        )

        if language is not None:
            transcript_language = language
        else:
            transcript_language = resolve_transcript_language(language_detected, raw_segments)

        segments = []
        for raw_segment in raw_segments:
            text = str(raw_segment.get("text", "")).strip()
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    id=len(segments),
                    start=float(raw_segment["start"]),
                    end=float(raw_segment["end"]),
                    text=text,
                )
            )

        transcript = Transcript(
            engine=engine,
            model=model,
            language=transcript_language,
            duration=context.job.duration,
            segments=segments,
        )
        write_transcript(context.project_dir, transcript)
        return str(TRANSCRIPT_PATH)


def resolve_transcript_language(
    detected_language: Optional[str],
    segments: list[dict],
) -> Optional[str]:
    if detected_language != "ja":
        return detected_language

    text = "".join(str(segment.get("text", "")) for segment in segments)
    if _contains_cjk(text):
        return detected_language

    non_whitespace_chars = [char for char in text if not char.isspace()]
    if not non_whitespace_chars:
        logger.warning("Whisper detected Japanese but transcript text has no CJK characters")
        return None

    ascii_letters = sum(1 for char in non_whitespace_chars if char.isascii() and char.isalpha())
    if ascii_letters / len(non_whitespace_chars) > _LATIN_DOMINANCE_THRESHOLD:
        return "en"

    logger.warning("Whisper detected Japanese but transcript text has no CJK characters")
    return None


def _contains_cjk(text: str) -> bool:
    return any(start <= ord(char) <= end for char in text for start, end in _CJK_RANGES)
