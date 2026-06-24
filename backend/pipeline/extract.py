from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, Protocol

from core.artifacts import AUDIO_PATH, THUMBNAIL_PATH
from core.errors import StageError
from pipeline.stage import PipelineContext, Stage
from schemas.enums import StageName

logger = logging.getLogger(__name__)


class AudioExtractor(Protocol):
    def probe(self, video_path: str) -> tuple[bool, float]: ...

    def extract(
        self,
        video_path: str,
        out_path: Path,
        options: Dict[str, object],
        progress_cb: Callable[[float], None],
    ) -> None: ...

    def extract_thumbnail(
        self,
        video_path: str,
        out_path: Path,
        offset_seconds: float,
        width: int,
    ) -> None: ...


class ExtractStage(Stage):
    name = StageName.extract

    def __init__(self, adapter: AudioExtractor) -> None:
        self.adapter = adapter

    def run(self, context: PipelineContext) -> str:
        has_audio, duration = self.adapter.probe(context.job.video_path)
        context.job.duration = duration
        if not has_audio:
            raise StageError(code="NO_AUDIO_TRACK", message="Input video has no audio track")

        self.adapter.extract(
            context.job.video_path,
            context.project_dir / AUDIO_PATH,
            {
                "duration": duration,
                "sample_rate": context.config.extract_sample_rate,
                "channels": context.config.extract_channels,
                "codec": context.config.extract_codec,
            },
            context.report_progress,
        )
        try:
            self.adapter.extract_thumbnail(
                context.job.video_path,
                context.project_dir / THUMBNAIL_PATH,
                context.config.thumbnail_offset_seconds,
                context.config.thumbnail_width,
            )
        except Exception as exc:
            logger.warning("thumbnail generation failed for job %s: %s", context.job.job_id, exc)
        return str(AUDIO_PATH)
