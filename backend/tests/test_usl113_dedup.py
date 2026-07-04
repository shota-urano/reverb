from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional

import pytest

from core.artifacts import read_translation, write_transcript
from core.config import BackendConfig
from core.job_store import JobStore
from pipeline.stage import PipelineContext
from pipeline.translate import TranslateStage, _group_source, dedup_adjacent_groups
from schemas.artifacts import Transcript, TranscriptSegment
from schemas.settings import default_job_settings


class _RecordingTranslator:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, object]]] = []

    def generate_glossary(
        self, transcript: str, model: str, source_lang: Optional[str], max_terms: int
    ) -> list[dict[str, str]]:
        return []

    def warm_up(self, model: str, system_prompt: str) -> None:
        pass

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
        return ["翻訳です。"]


def test_adjacent_similar_groups_are_merged_with_representative_source() -> None:
    first = [_segment(1, 0.0, 1.0, "Hello, world!")]
    second = [_segment(2, 1.0, 2.5, "hello world")]

    result = dedup_adjacent_groups([first, second], 0.9, True)

    assert len(result) == 1
    assert [segment.id for segment in result[0]] == [1, 2]
    assert result[0][-1].end == 2.5
    assert _group_source(result[0]) == "Hello, world!"
    assert second[0].text == "hello world"


def test_adjacent_groups_below_threshold_are_not_merged() -> None:
    groups = [
        [_segment(1, 0.0, 1.0, "The first sentence.")],
        [_segment(2, 1.0, 2.0, "A completely different thought.")],
    ]

    result = dedup_adjacent_groups(groups, 0.9, True)

    assert result == groups
    assert len(result) == 2


def test_similarity_equal_to_threshold_is_merged() -> None:
    groups = [
        [_segment(1, 0.0, 1.0, "Same sentence.")],
        [_segment(2, 1.0, 2.0, "same sentence")],
    ]

    result = dedup_adjacent_groups(groups, 1.0, True)

    assert len(result) == 1


def test_non_adjacent_repetition_is_not_merged() -> None:
    groups = [
        [_segment(1, 0.0, 1.0, "Repeated sentence.")],
        [_segment(2, 1.0, 2.0, "Different sentence.")],
        [_segment(3, 2.0, 3.0, "Repeated sentence.")],
    ]

    result = dedup_adjacent_groups(groups, 0.9, True)

    assert [[segment.id for segment in group] for group in result] == [[1], [2], [3]]


def test_disabled_returns_input_without_merging() -> None:
    groups = [
        [_segment(1, 0.0, 1.0, "Same sentence.")],
        [_segment(2, 1.0, 2.0, "Same sentence.")],
    ]

    result = dedup_adjacent_groups(groups, 0.9, False)

    assert result is groups


def test_non_linguistic_group_is_not_merged() -> None:
    groups = [
        [_segment(1, 0.0, 1.0, "...")],
        [_segment(2, 1.0, 2.0, "...")],
    ]

    result = dedup_adjacent_groups(groups, 0.9, True)

    assert result == groups
    assert len(result) == 2


def test_empty_group_is_not_merged() -> None:
    group = [_segment(1, 0.0, 1.0, "Same sentence.")]

    result = dedup_adjacent_groups([group, [], group], 0.9, True)

    assert result == [group, [], group]


def test_dedup_config_defaults_env_validation_and_project_dir_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert BackendConfig().translate_dedup_enabled is True
    assert BackendConfig().translate_dedup_similarity == 0.9

    monkeypatch.setenv("REVERB_TRANSLATE_DEDUP_ENABLED", "false")
    monkeypatch.setenv("REVERB_TRANSLATE_DEDUP_SIMILARITY", "0.95")
    config = BackendConfig()
    copied = config.with_projects_dir(tmp_path)

    assert config.translate_dedup_enabled is False
    assert config.translate_dedup_similarity == 0.95
    assert copied.translate_dedup_enabled is False
    assert copied.translate_dedup_similarity == 0.95
    with pytest.raises(ValueError):
        dataclasses.replace(config, translate_dedup_similarity=-0.1)
    with pytest.raises(ValueError):
        dataclasses.replace(config, translate_dedup_similarity=1.1)


def test_translate_stage_uses_representative_source_and_merged_timing(tmp_path: Path) -> None:
    config = BackendConfig(translate_retry_initial_wait=0.0).with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record = store.create("/tmp/input.mp4", default_job_settings(config))
    write_transcript(
        record.project_dir,
        Transcript(
            engine=config.default_stt_engine,
            model=record.settings.stt.model,
            language="en",
            duration=2.5,
            segments=[
                _segment(1, 0.0, 1.0, "Hello, world!"),
                _segment(2, 1.0, 2.5, "hello world"),
            ],
        ),
    )
    translator = _RecordingTranslator()

    TranslateStage(translator).run(
        PipelineContext(config, record, record.project_dir),
    )

    translation = read_translation(record.project_dir)
    assert len(translation.segments) == 1
    assert translation.segments[0].end == 2.5
    assert translation.segments[0].source == "Hello, world!"
    assert translator.calls[0][-1]["text"] == "Hello, world!"
    assert translator.calls[0][-1]["end"] == 2.5


def _segment(segment_id: int, start: float, end: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(id=segment_id, start=start, end=end, text=text)
