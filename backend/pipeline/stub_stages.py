from __future__ import annotations

from typing import List

from pipeline.stage import PipelineContext, Stage
from schemas.enums import StageName


class StubStage(Stage):
    def __init__(self, name: StageName, artifact: str) -> None:
        self.name = name
        self.artifact = artifact

    def run(self, context: PipelineContext) -> str:
        target = context.project_dir / self.artifact
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix == ".json":
            target.write_text(self._json_payload(context), encoding="utf-8")
        else:
            target.write_bytes(b"")
        return self.artifact

    def _json_payload(self, context: PipelineContext) -> str:
        if self.name == StageName.subtitle:
            return '{"version":1,"cues":[]}\n'
        if self.name == StageName.transcribe:
            return (
                '{"version":1,"engine":"mlx-whisper","model":'
                f'"{context.job.settings.stt.model}","language":null,'
                '"duration":0.0,"segments":[]}\n'
            )
        if self.name == StageName.translate:
            return (
                '{"version":1,"model":'
                f'"{context.job.settings.translate.model}","sourceLanguage":null,'
                '"targetLanguage":"ja","segments":[]}\n'
            )
        if self.name == StageName.extract:
            return '{"version":1}\n'
        return "{}\n"


def build_stub_stages() -> List[Stage]:
    return [
        StubStage(StageName.extract, "audio.wav"),
        StubStage(StageName.transcribe, "transcript.json"),
        StubStage(StageName.translate, "translation.json"),
        StubStage(StageName.subtitle, "subtitles.json"),
        StubStage(StageName.tts, "tts/manifest.json"),
        StubStage(StageName.mix, "voiceover.wav"),
    ]
