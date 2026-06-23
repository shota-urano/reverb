from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional

import pytest

from core.artifacts import read_translation, write_transcript
from core.config import BackendConfig
from core.errors import StageError
from core.job_store import JobStore
from pipeline.stage import PipelineContext
from pipeline.translate import TranslateStage
from schemas.artifacts import Transcript, TranscriptSegment, Translation
from schemas.settings import default_job_settings


class FakeTranslator:
    def __init__(self, responses: Optional[list[list[str]]] = None) -> None:
        self.responses = responses if responses is not None else []
        self.warm_up_calls = 0
        self.calls: list[list[dict[str, object]]] = []

    def warm_up(self, model: str, system_prompt: str) -> None:
        self.warm_up_calls += 1

    def translate(
        self,
        segments: list[dict[str, object]],
        model: str,
        source_lang: Optional[str],
        system_prompt: str,
        context_window: int,
    ) -> list[str]:
        self.calls.append(segments)
        if self.responses:
            return self.responses.pop(0)
        return []


def test_single_empty_translation_falls_back_to_source(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    translator = FakeTranslator(responses=[[""]])
    caplog.set_level("WARNING", logger="pipeline.translate")

    translation = _run_translate_stage(
        tmp_path,
        translator,
        [TranscriptSegment(id=1, start=0.0, end=1.0, text="Hello.")],
        config_overrides={
            "translate_max_retries": 0,
            "translate_retry_initial_wait": 0.0,
        },
    )

    assert [segment.target for segment in translation.segments] == ["Hello."]
    assert len(translator.calls) == 1
    assert "using source text for 1 segment(s)" in caplog.text


def test_majority_empty_translations_after_retries_raise_translate_incomplete(
    tmp_path: Path,
) -> None:
    translator = FakeTranslator(responses=[["", "", "三番目です。"]])

    with pytest.raises(StageError) as exc_info:
        _run_translate_stage(
            tmp_path,
            translator,
            [
                TranscriptSegment(id=1, start=0.0, end=1.0, text="First."),
                TranscriptSegment(id=2, start=1.0, end=2.0, text="Second."),
                TranscriptSegment(id=3, start=2.0, end=3.0, text="Third."),
            ],
            config_overrides={
                "translate_max_retries": 0,
                "translate_retry_initial_wait": 0.0,
                "translate_fallback_threshold": 0.5,
            },
        )

    assert exc_info.value.code == "TRANSLATE_INCOMPLETE"
    assert exc_info.value.retryable is True


def test_symbol_digit_whitespace_only_segment_passes_through_without_llm_call(
    tmp_path: Path,
) -> None:
    translator = FakeTranslator()

    translation = _run_translate_stage(
        tmp_path,
        translator,
        [TranscriptSegment(id=1, start=0.0, end=1.0, text="  ! 123  ")],
    )

    assert [segment.target for segment in translation.segments] == ["  ! 123  "]
    assert translator.warm_up_calls == 0
    assert translator.calls == []


def test_normal_translations_are_returned_unchanged(tmp_path: Path) -> None:
    translator = FakeTranslator(responses=[["こんにちは。", "世界です。"]])

    translation = _run_translate_stage(
        tmp_path,
        translator,
        [
            TranscriptSegment(id=1, start=0.0, end=1.0, text="Hello."),
            TranscriptSegment(id=2, start=1.0, end=2.0, text="World."),
        ],
    )

    assert [segment.target for segment in translation.segments] == [
        "こんにちは。",
        "世界です。",
    ]
    assert len(translator.calls) == 1


def test_non_linguistic_segments_remain_in_context_window_for_adjacent_targets(
    tmp_path: Path,
) -> None:
    translator = FakeTranslator(responses=[["こんにちは。", "世界です。"]])

    translation = _run_translate_stage(
        tmp_path,
        translator,
        [
            TranscriptSegment(id=1, start=0.0, end=1.0, text="Hello."),
            TranscriptSegment(id=2, start=1.0, end=2.0, text="!!!"),
            TranscriptSegment(id=3, start=2.0, end=3.0, text="World."),
        ],
        config_overrides={"translate_chunk_size": 3},
    )

    assert [segment.target for segment in translation.segments] == [
        "こんにちは。",
        "!!!",
        "世界です。",
    ]
    assert translator.calls[0] == [
        {
            "id": 1,
            "start": 0.0,
            "end": 1.0,
            "text": "Hello.",
            "contextOnly": False,
        },
        {
            "id": 2,
            "start": 1.0,
            "end": 2.0,
            "text": "!!!",
            "contextOnly": True,
        },
        {
            "id": 3,
            "start": 2.0,
            "end": 3.0,
            "text": "World.",
            "contextOnly": False,
        },
    ]


def test_translate_fallback_threshold_config_env_validation_and_project_dir_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REVERB_TRANSLATE_FALLBACK_THRESHOLD", "0.75")

    config = BackendConfig()
    copied = config.with_projects_dir(tmp_path)

    assert config.translate_fallback_threshold == 0.75
    assert copied.translate_fallback_threshold == 0.75
    with pytest.raises(ValueError):
        dataclasses.replace(config, translate_fallback_threshold=0.0)
    with pytest.raises(ValueError):
        dataclasses.replace(config, translate_fallback_threshold=1.1)


def _run_translate_stage(
    tmp_path: Path,
    translator: FakeTranslator,
    segments: list[TranscriptSegment],
    *,
    config_overrides: Optional[dict[str, object]] = None,
) -> Translation:
    config = BackendConfig(
        **{"translate_retry_initial_wait": 0.0, **(config_overrides or {})},
    ).with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record = store.create("/tmp/input.mp4", default_job_settings(config))
    transcript = Transcript(
        engine=config.default_stt_engine,
        model=record.settings.stt.model,
        language="en",
        duration=10.0,
        segments=segments,
    )
    write_transcript(record.project_dir, transcript)

    stage = TranslateStage(translator)
    stage.run(PipelineContext(config, record, record.project_dir))
    return read_translation(record.project_dir)
