from __future__ import annotations

from pathlib import Path
from typing import List

from core.job_store import JobStore, invalidate_downstream_stages
from schemas.enums import StageName, StageState
from schemas.settings import JobSettings, MixSettings, STTSettings, TTSSettings, TranslateSettings
from services.pipeline_runner import PipelineRunner


def _settings(translate_model: str = "qwen3:30b") -> JobSettings:
    return JobSettings(
        stt=STTSettings(model="large-v3", language=None),
        translate=TranslateSettings(model=translate_model),
        tts=TTSSettings(speakerId=13, styleId=0),
        mix=MixSettings(jaVolume=1.0, originalVolume=0.08),
    )


def test_translate_settings_change_invalidates_translate_and_downstream(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    record = store.create("/tmp/input.mp4", _settings())
    for name in StageName:
        stage = record.stages[name]
        stage.status = StageState.done
        stage.progress = 1.0
        stage.artifact = f"{name.value}.artifact"
        (record.project_dir / stage.artifact).write_text(name.value, encoding="utf-8")
    record.stages[StageName.extract].artifact = "audio.wav"
    (record.project_dir / "audio.wav").write_bytes(b"audio")
    record.stages[StageName.transcribe].artifact = "transcript.json"
    (record.project_dir / "transcript.json").write_text("{}", encoding="utf-8")
    record.stages[StageName.translate].artifact = "translation.json"
    (record.project_dir / "translation.json").write_text("{}", encoding="utf-8")
    record.stages[StageName.subtitle].artifact = "subtitles.json"
    (record.project_dir / "subtitles.json").write_text("{}", encoding="utf-8")
    record.stages[StageName.tts].artifact = "tts/cue_0000.wav"
    (record.project_dir / "tts").mkdir(exist_ok=True)
    (record.project_dir / "tts" / "cue_0000.wav").write_bytes(b"tts")
    record.stages[StageName.mix].artifact = "voiceover.wav"
    (record.project_dir / "voiceover.wav").write_bytes(b"mix")
    store.save(record)

    changed = _settings(translate_model="gemma3:27b")

    invalidated = invalidate_downstream_stages(store, record.job_id, record.video_path, changed)

    assert invalidated == [
        StageName.translate,
        StageName.subtitle,
        StageName.tts,
        StageName.mix,
    ]
    persisted = JobStore(tmp_path).get(record.job_id)
    assert persisted.settings == changed
    assert persisted.stages[StageName.extract].status == StageState.done
    assert persisted.stages[StageName.transcribe].status == StageState.done
    assert persisted.stages[StageName.translate].status == StageState.pending
    assert persisted.stages[StageName.subtitle].status == StageState.pending
    assert persisted.stages[StageName.tts].status == StageState.pending
    assert persisted.stages[StageName.mix].status == StageState.pending
    assert (record.project_dir / "audio.wav").exists()
    assert (record.project_dir / "transcript.json").exists()
    assert not (record.project_dir / "translation.json").exists()
    assert not (record.project_dir / "subtitles.json").exists()
    assert not (record.project_dir / "tts" / "cue_0000.wav").exists()
    assert not (record.project_dir / "voiceover.wav").exists()


class _CountingStage:
    def __init__(self, name: StageName, calls: List[StageName]) -> None:
        self.name = name
        self.calls = calls

    def run(self, context) -> str:
        self.calls.append(self.name)
        return f"{self.name.value}.artifact"


def test_resume_after_invalidation_runs_only_pending_stages(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    record = store.create("/tmp/input.mp4", _settings())
    for name in (StageName.extract, StageName.transcribe):
        record.stages[name].status = StageState.done
        record.stages[name].progress = 1.0
    for name in (StageName.translate, StageName.subtitle, StageName.tts, StageName.mix):
        record.stages[name].status = StageState.pending
        record.stages[name].progress = 0.0
    store.save(record)

    calls: List[StageName] = []
    runner = PipelineRunner(
        config=None,
        store=store,
        stages=[_CountingStage(name, calls) for name in StageName],
        notify=lambda record: None,
    )

    runner.run(record)

    assert calls == [
        StageName.translate,
        StageName.subtitle,
        StageName.tts,
        StageName.mix,
    ]
