from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional

import pytest

from core.artifacts import read_translation, write_transcript
from core.errors import StageError
from core.config import BackendConfig
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

    def generate_glossary(
        self, transcript: str, model: str, source_lang: Optional[str], max_terms: int
    ) -> list[dict[str, str]]:
        return []

    def warm_up(self, model: str, system_prompt: str) -> None:
        self.warm_up_calls += 1

    def translate(
        self,
        segments: list[dict[str, object]],
        model: str,
        source_lang: Optional[str],
        system_prompt: str,
        context_window: int,
        glossary: list[dict[str, str]],
    ) -> list[str]:
        self.calls.append(segments)
        if self.responses:
            return self.responses.pop(0)
        return []

    def polish(self, segments, model, system_prompt, temperature):
        return [segment["text"] for segment in segments]


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


def test_empty_group_translation_falls_back_without_blocking_following_groups(
    tmp_path: Path,
) -> None:
    translator = FakeTranslator(responses=[[""], ["二番目です。"]])

    translation = _run_translate_stage(
        tmp_path,
        translator,
        [
            TranscriptSegment(id=1, start=0.0, end=1.0, text="First."),
            TranscriptSegment(id=2, start=3.0, end=4.0, text="Second."),
        ],
        config_overrides={
            "translate_max_retries": 0,
            "translate_retry_initial_wait": 0.0,
            "translate_fallback_threshold": 0.5,
        },
    )

    assert [segment.target for segment in translation.segments] == ["First.", "二番目です。"]
    assert len(translator.calls) == 2


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
    translator = FakeTranslator(responses=[["こんにちは。"], ["世界です。"]])

    translation = _run_translate_stage(
        tmp_path,
        translator,
        [
            TranscriptSegment(id=1, start=0.0, end=1.0, text="Hello."),
            TranscriptSegment(id=2, start=3.0, end=4.0, text="World."),
        ],
    )

    assert [segment.target for segment in translation.segments] == [
        "こんにちは。",
        "世界です。",
    ]
    assert len(translator.calls) == 2


def test_non_linguistic_segments_remain_in_context_window_for_adjacent_targets(
    tmp_path: Path,
) -> None:
    translator = FakeTranslator(responses=[["こんにちは。"], ["世界です。"]])

    translation = _run_translate_stage(
        tmp_path,
        translator,
        [
            TranscriptSegment(id=1, start=0.0, end=1.0, text="Hello."),
            TranscriptSegment(id=2, start=1.0, end=2.0, text="!!!"),
            TranscriptSegment(id=3, start=2.0, end=3.0, text="World."),
        ],
        config_overrides={"translate_chunk_size": 3, "translate_chunk_groups": 2},
    )

    assert [segment.target for segment in translation.segments] == [
        "こんにちは。",
        "!!!",
        "世界です。",
    ]
    assert translator.calls[1] == [
        {
            "id": 1,
            "start": 0.0,
            "end": 1.0,
            "text": "Hello.",
            "target": "こんにちは。",
            "contextOnly": True,
        },
        {
            "id": 2,
            "start": 1.0,
            "end": 2.0,
            "text": "!!!",
            "target": "!!!",
            "contextOnly": True,
        },
        {
            "id": 3,
            "start": 2.0,
            "end": 3.0,
            "text": "World.",
            "contextOnly": False,
            "targetChars": 8,
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
        **{
            "translate_retry_initial_wait": 0.0,
            "translate_chunk_groups": 1,
            **(config_overrides or {}),
        },
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


def test_majority_fallback_exceeds_threshold_raises_stage_error(
    tmp_path: Path,
) -> None:
    # 3グループすべてが空応答 -> source fallback -> 閾値 (0.5) 超過で StageError
    translator = FakeTranslator(responses=[[""], [""], [""]])

    with pytest.raises(StageError) as exc_info:
        _run_translate_stage(
            tmp_path,
            translator,
            [
                TranscriptSegment(id=1, start=0.0, end=1.0, text="First."),
                TranscriptSegment(id=2, start=3.0, end=4.0, text="Second."),
                TranscriptSegment(id=3, start=6.0, end=7.0, text="Third."),
            ],
            config_overrides={
                "translate_max_retries": 0,
                "translate_retry_initial_wait": 0.0,
                "translate_fallback_threshold": 0.5,
            },
        )

    assert exc_info.value.code == "TRANSLATE_INCOMPLETE"


def test_single_fallback_within_threshold_succeeds(
    tmp_path: Path,
) -> None:
    # 3グループ中1つだけ fallback (1/3 <= 0.5) -> 成功
    translator = FakeTranslator(responses=[[""], ["二番目。"], ["三番目。"]])

    translation = _run_translate_stage(
        tmp_path,
        translator,
        [
            TranscriptSegment(id=1, start=0.0, end=1.0, text="First."),
            TranscriptSegment(id=2, start=3.0, end=4.0, text="Second."),
            TranscriptSegment(id=3, start=6.0, end=7.0, text="Third."),
        ],
        config_overrides={
            "translate_max_retries": 0,
            "translate_retry_initial_wait": 0.0,
            "translate_fallback_threshold": 0.5,
        },
    )

    # fallback したグループ1は source text のまま
    assert translation.segments[0].target == "First."
    assert translation.segments[1].target == "二番目。"
    assert translation.segments[2].target == "三番目。"
