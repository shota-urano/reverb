from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Protocol

from core.artifacts import AUDIO_PATH
from core.errors import StageError
from pipeline.stage import PipelineContext, Stage
from schemas.enums import StageName


class AudioExtractor(Protocol):
    def probe(self, video_path: str) -> tuple[bool, float]: ...

    def extract(
        self,
        video_path: str,
        out_path: Path,
        options: Dict[str, object],
        progress_cb: Callable[[float], None],
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
        return str(AUDIO_PATH)
