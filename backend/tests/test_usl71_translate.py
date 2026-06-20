from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.artifacts import read_translation, write_transcript
from core.config import BackendConfig
from core.errors import StageError
from core.job_store import JobRecord, JobStore
from pipeline.stub_stages import StubStage
from pipeline.translate import TranslateStage
from schemas.artifacts import Transcript, TranscriptSegment
from schemas.enums import JobState, StageName, StageState
from schemas.settings import default_job_settings
from services.pipeline_runner import PipelineRunner


class FakeTranslator:
    def __init__(
        self,
        *,
        responses: Optional[list[list[str]]] = None,
        error: Optional[StageError] = None,
    ) -> None:
        self.responses = responses if responses is not None else []
        self.error = error
        self.calls = []

    def translate(
        self,
        segments: list[dict],
        model: str,
        source_lang: Optional[str],
        system_prompt: str,
        context_window: int,
    ) -> list[str]:
        self.calls.append(
            {
                "segments": segments,
                "model": model,
                "source_lang": source_lang,
                "system_prompt": system_prompt,
                "context_window": context_window,
            }
        )
        if self.error:
            raise self.error
        if self.responses:
            return self.responses.pop(0)
        return [f"訳{segment['id']}" for segment in segments if not segment.get("contextOnly")]


def test_translate_happy_path_writes_translation_artifact_and_progress(tmp_path: Path) -> None:
    translator = FakeTranslator(
        responses=[
            ["こんにちは。", "世界です。"],
            ["続きです。"],
        ]
    )

    record, notifications = _run_pipeline(
        tmp_path,
        translator,
        segments=[
            TranscriptSegment(id=0, start=0.0, end=1.0, text="Hello."),
            TranscriptSegment(id=1, start=1.0, end=2.0, text="World."),
            TranscriptSegment(id=2, start=2.0, end=3.0, text="Again."),
        ],
        chunk_size=2,
    )

    translation = read_translation(record.project_dir)
    assert record.status == JobState.done
    assert record.stages[StageName.translate].status == StageState.done
    assert record.stages[StageName.translate].artifact == "translation.json"
    assert translation.model == record.settings.translate.model
    assert translation.sourceLanguage == "en"
    assert translation.targetLanguage == "ja"
    assert [segment.id for segment in translation.segments] == [0, 1, 2]
    assert [segment.source for segment in translation.segments] == ["Hello.", "World.", "Again."]
    assert [segment.target for segment in translation.segments] == [
        "こんにちは。",
        "世界です。",
        "続きです。",
    ]
    assert translator.calls[0]["model"] == record.settings.translate.model
    assert translator.calls[0]["source_lang"] == "en"
    assert translator.calls[1]["segments"][0]["contextOnly"] is True
    assert translator.calls[1]["segments"][0]["id"] == 0
    translate_progress = [
        snapshot.stages[2].progress
        for snapshot in notifications
        if snapshot.currentStage == "translate"
    ]
    assert translate_progress[0] == 0.0
    assert translate_progress[-1] == 1.0


def test_translate_all_empty_segments_writes_empty_segments_without_error(tmp_path: Path) -> None:
    record, _ = _run_pipeline(
        tmp_path,
        FakeTranslator(),
        segments=[
            TranscriptSegment(id=0, start=0.0, end=1.0, text=""),
            TranscriptSegment(id=1, start=1.0, end=2.0, text="   "),
        ],
    )

    translation = read_translation(record.project_dir)
    assert record.status == JobState.done
    assert record.stages[StageName.translate].status == StageState.done
    assert translation.segments == []


def test_translate_ollama_unavailable_error_code_is_preserved(tmp_path: Path) -> None:
    record, _ = _run_pipeline(
        tmp_path,
        FakeTranslator(error=StageError("OLLAMA_UNAVAILABLE", "Ollama unavailable", True)),
    )

    assert record.status == JobState.failed
    assert record.error is not None
    assert record.error.code == "OLLAMA_UNAVAILABLE"
    assert record.error.retryable is True
    assert record.stages[StageName.translate].status == StageState.failed


def test_translate_model_missing_error_code_is_preserved(tmp_path: Path) -> None:
    record, _ = _run_pipeline(
        tmp_path,
        FakeTranslator(error=StageError("MODEL_MISSING", "Run ollama pull qwen3:30b")),
    )

    assert record.status == JobState.failed
    assert record.error is not None
    assert record.error.code == "MODEL_MISSING"
    assert record.stages[StageName.translate].status == StageState.failed


def test_translate_misalign_after_retry_fails_with_translate_misalign(tmp_path: Path) -> None:
    record, _ = _run_pipeline(
        tmp_path,
        FakeTranslator(responses=[["一つだけ。"], ["まだ一つだけ。"]]),
        segments=[
            TranscriptSegment(id=0, start=0.0, end=1.0, text="First."),
            TranscriptSegment(id=1, start=1.0, end=2.0, text="Second."),
        ],
    )

    assert record.status == JobState.failed
    assert record.error is not None
    assert record.error.code == "TRANSLATE_MISALIGN"
    assert record.stages[StageName.translate].status == StageState.failed


def _run_pipeline(
    tmp_path: Path,
    translator: FakeTranslator,
    *,
    segments: Optional[list[TranscriptSegment]] = None,
    chunk_size: int = 10,
) -> tuple[JobRecord, list]:
    config = BackendConfig(
        translate_chunk_size=chunk_size,
        translate_context_window=2,
    ).with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record = store.create("/tmp/input.mp4", default_job_settings(config))
    transcript = Transcript(
        engine=config.default_stt_engine,
        model=record.settings.stt.model,
        language="en",
        duration=10.0,
        segments=(
            segments
            if segments is not None
            else [
                TranscriptSegment(id=0, start=0.0, end=1.0, text="Hello."),
            ]
        ),
    )
    write_transcript(record.project_dir, transcript)

    notifications = []
    runner = PipelineRunner(
        config,
        store,
        [
            TranslateStage(translator),
            StubStage(StageName.subtitle, "subtitles.json"),
            StubStage(StageName.tts, "tts/cue_0000.wav"),
            StubStage(StageName.mix, "voiceover.wav"),
        ],
        lambda job: notifications.append(job.snapshot()),
    )

    runner.run(record)
    return record, notifications
