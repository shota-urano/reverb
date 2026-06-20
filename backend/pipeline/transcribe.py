from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional, Protocol

from core.artifacts import AUDIO_PATH, TRANSCRIPT_PATH, write_transcript
from pipeline.stage import PipelineContext, Stage
from schemas.artifacts import Transcript, TranscriptSegment
from schemas.enums import StageName


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
            language=language_detected,
            duration=context.job.duration,
            segments=segments,
        )
        write_transcript(context.project_dir, transcript)
        return str(TRANSCRIPT_PATH)
