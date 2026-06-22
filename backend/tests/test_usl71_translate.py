from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

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
        errors: Optional[list[StageError]] = None,
        error: Optional[StageError] = None,
        warm_up_error: Optional[StageError] = None,
    ) -> None:
        self.responses = responses if responses is not None else []
        self.errors = errors if errors is not None else []
        self.error = error
        self.warm_up_error = warm_up_error
        self.calls = []
        self.events = []

    def warm_up(self, model: str, system_prompt: str) -> None:
        self.events.append("warm_up")
        if self.warm_up_error:
            raise self.warm_up_error

    def translate(
        self,
        segments: list[dict],
        model: str,
        source_lang: Optional[str],
        system_prompt: str,
        context_window: int,
    ) -> list[str]:
        self.events.append("translate")
        self.calls.append(
            {
                "segments": segments,
                "model": model,
                "source_lang": source_lang,
                "system_prompt": system_prompt,
                "context_window": context_window,
            }
        )
        if self.errors:
            raise self.errors.pop(0)
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


def test_translate_symbol_only_segment_passthrough_without_ollama(tmp_path: Path) -> None:
    translator = FakeTranslator()

    record, _ = _run_pipeline(
        tmp_path,
        translator,
        segments=[
            TranscriptSegment(id=0, start=0.0, end=1.0, text="."),
        ],
    )

    translation = read_translation(record.project_dir)
    assert record.status == JobState.done
    assert [(segment.id, segment.source, segment.target) for segment in translation.segments] == [
        (0, ".", ".")
    ]
    assert translator.events == []


def test_translate_omits_empty_segments_when_mixed_with_translated_segments(
    tmp_path: Path,
) -> None:
    translator = FakeTranslator(responses=[["こんにちは。"]])

    record, _ = _run_pipeline(
        tmp_path,
        translator,
        segments=[
            TranscriptSegment(id=0, start=0.0, end=1.0, text=""),
            TranscriptSegment(id=1, start=1.0, end=2.0, text="Hello."),
            TranscriptSegment(id=2, start=2.0, end=3.0, text="   "),
            TranscriptSegment(id=3, start=3.0, end=4.0, text="."),
        ],
    )

    translation = read_translation(record.project_dir)
    assert record.status == JobState.done
    assert [segment.id for segment in translation.segments] == [1, 3]
    assert [segment.source for segment in translation.segments] == ["Hello.", "."]
    assert [segment.target for segment in translation.segments] == ["こんにちは。", "."]
    assert [segment["id"] for segment in translator.calls[0]["segments"]] == [1]


def test_translate_ollama_unavailable_error_code_is_preserved(tmp_path: Path) -> None:
    record, _ = _run_pipeline(
        tmp_path,
        FakeTranslator(error=StageError("OLLAMA_UNAVAILABLE", "Ollama unavailable", True)),
        config_overrides={"translate_retry_initial_wait": 0.0},
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
        config_overrides={
            "translate_max_retries": 1,
            "translate_retry_initial_wait": 0.0,
        },
    )

    assert record.status == JobState.failed
    assert record.error is not None
    assert record.error.code == "TRANSLATE_MISALIGN"
    assert record.error.retryable is True
    assert record.stages[StageName.translate].status == StageState.failed


def test_translate_empty_target_for_text_segment_retries_then_fails(tmp_path: Path) -> None:
    translator = FakeTranslator(responses=[[""], ["   "]])

    record, _ = _run_pipeline(
        tmp_path,
        translator,
        segments=[
            TranscriptSegment(id=0, start=0.0, end=1.0, text="Hello."),
        ],
        config_overrides={
            "translate_max_retries": 1,
            "translate_retry_initial_wait": 0.0,
        },
    )

    assert record.status == JobState.failed
    assert record.error is not None
    assert record.error.code == "TRANSLATE_INCOMPLETE"
    assert record.error.retryable is True
    assert record.stages[StageName.translate].status == StageState.failed
    assert len(translator.calls) == 2


def test_translate_retries_retryable_stage_error_then_succeeds(tmp_path: Path) -> None:
    translator = FakeTranslator(
        errors=[StageError("OLLAMA_UNAVAILABLE", "timed out", retryable=True)],
        responses=[["リトライ後に成功。"]],
    )

    record, _ = _run_pipeline(
        tmp_path,
        translator,
        config_overrides={
            "translate_max_retries": 3,
            "translate_retry_initial_wait": 0.0,
        },
    )

    translation = read_translation(record.project_dir)
    assert record.status == JobState.done
    assert [segment.target for segment in translation.segments] == ["リトライ後に成功。"]
    assert len(translator.calls) == 2


def test_translate_fails_after_retry_limit_is_exceeded(tmp_path: Path) -> None:
    translator = FakeTranslator(
        errors=[
            StageError("OLLAMA_UNAVAILABLE", "timed out", retryable=True),
            StageError("OLLAMA_UNAVAILABLE", "timed out again", retryable=True),
            StageError("OLLAMA_UNAVAILABLE", "still timed out", retryable=True),
        ]
    )

    record, _ = _run_pipeline(
        tmp_path,
        translator,
        config_overrides={
            "translate_max_retries": 2,
            "translate_retry_initial_wait": 0.0,
        },
    )

    assert record.status == JobState.failed
    assert record.error is not None
    assert record.error.code == "OLLAMA_UNAVAILABLE"
    assert record.error.retryable is True
    assert len(translator.calls) == 3


def test_translate_warms_up_before_first_chunk_and_continues_after_failure(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    translator = FakeTranslator(
        responses=[["ウォームアップ失敗後も続行。"]],
        warm_up_error=StageError("OLLAMA_UNAVAILABLE", "warm-up timeout", retryable=True),
    )

    record, _ = _run_pipeline(tmp_path, translator, caplog=caplog)

    translation = read_translation(record.project_dir)
    assert record.status == JobState.done
    assert [segment.target for segment in translation.segments] == ["ウォームアップ失敗後も続行。"]
    assert translator.events[:2] == ["warm_up", "translate"]
    assert "Ollama warm-up failed; continuing with translate stage." in caplog.text


def _run_pipeline(
    tmp_path: Path,
    translator: FakeTranslator,
    *,
    segments: Optional[list[TranscriptSegment]] = None,
    chunk_size: int = 10,
    config_overrides: Optional[dict[str, object]] = None,
    caplog: Optional[pytest.LogCaptureFixture] = None,
) -> tuple[JobRecord, list]:
    if caplog is not None:
        caplog.set_level("WARNING", logger="pipeline.translate")
    overrides = config_overrides or {}
    config = BackendConfig(
        translate_chunk_size=chunk_size,
        translate_context_window=2,
        **overrides,
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
