from __future__ import annotations

from typing import List

from core.artifacts import write_subtitles, write_transcript, write_translation
from pipeline.stage import PipelineContext, Stage
from schemas.artifacts import Subtitles, Transcript, Translation
from schemas.enums import StageName


class StubStage(Stage):
    def __init__(self, name: StageName, artifact: str) -> None:
        self.name = name
        self.artifact = artifact

    def run(self, context: PipelineContext) -> str:
        target = context.project_dir / self.artifact
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.name == StageName.transcribe:
            write_transcript(
                context.project_dir,
                Transcript(
                    engine=context.config.default_stt_engine,
                    model=context.job.settings.stt.model,
                    language=None,
                    duration=0.0,
                    segments=[],
                ),
            )
        elif self.name == StageName.translate:
            write_translation(
                context.project_dir,
                Translation(
                    model=context.job.settings.translate.model,
                    sourceLanguage=None,
                    targetLanguage="ja",
                    segments=[],
                ),
            )
        elif self.name == StageName.subtitle:
            write_subtitles(context.project_dir, Subtitles(cues=[]))
        else:
            target.write_bytes(b"")
        return self.artifact


def build_stub_stages() -> List[Stage]:
    return [
        StubStage(StageName.extract, "audio.wav"),
        StubStage(StageName.transcribe, "transcript.json"),
        StubStage(StageName.translate, "translation.json"),
        StubStage(StageName.subtitle, "subtitles.json"),
        StubStage(StageName.tts, "tts/cue_0000.wav"),
        StubStage(StageName.mix, "voiceover.wav"),
    ]
