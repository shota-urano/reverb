from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from core.config import BackendConfig
from pipeline.translate import _target_chars
from schemas.artifacts import TranscriptSegment, TranslationSegment
from test_usl110_dubbing_script import FakeTranslator, _inputs, _run_translate, _segment
from test_usl115_polish import _PolishTranslator, _run_pipeline


def test_target_chars_includes_capped_trailing_gap_and_speed_factor() -> None:
    segment = TranslationSegment(
        id=1,
        start=0.0,
        end=1.0,
        source="Short.",
        target="短いです。",
    )

    relaxed = _target_chars(
        segment,
        6.0,
        trailing_gap_seconds=2.0,
        gap_cap_seconds=2.5,
        speed_factor=1.3,
    )

    assert relaxed == 23
    assert relaxed > _target_chars(segment, 6.0)


def test_target_chars_legacy_mode_matches_original_budget() -> None:
    segment = TranslationSegment(
        id=1,
        start=2.0,
        end=3.0,
        source="Short.",
        target="短いです。",
    )

    assert _target_chars(
        segment,
        6.0,
        trailing_gap_seconds=10.0,
        gap_cap_seconds=0.0,
        speed_factor=1.0,
    ) == _target_chars(segment, 6.0)
    assert _target_chars(
        segment,
        6.0,
        trailing_gap_seconds=10.0,
        gap_cap_seconds=0.0,
        speed_factor=0.0,
    ) == _target_chars(segment, 6.0)


def test_translate_group_budget_looks_ahead_across_request_boundary(tmp_path: Path) -> None:
    translator = FakeTranslator(responses=[["第一訳。"], ["第二訳。"]])

    _run_translate(
        tmp_path,
        translator,
        [
            _segment(1, 0.0, 1.0, "First."),
            _segment(2, 11.0, 12.0, "Second."),
        ],
        translate_chunk_groups=1,
        translate_target_gap_cap_seconds=2.0,
        translate_target_speed_factor=1.3,
    )

    assert [
        _inputs(call)[0]["targetChars"] for call in translator.calls
    ] == [23, 8]


def test_polish_inputs_receive_relaxed_budget(tmp_path: Path) -> None:
    translator = _PolishTranslator(polish_responses=[["第一推敲。", "第二推敲。"]])
    segments = [
        TranscriptSegment(id=1, start=0.0, end=1.0, text="First."),
        TranscriptSegment(id=2, start=3.0, end=4.0, text="Second."),
    ]

    _run_pipeline(
        tmp_path,
        translator,
        segments=segments,
        translate_target_gap_cap_seconds=2.5,
        translate_target_speed_factor=1.3,
    )

    assert [
        item["targetChars"] for item in translator.polish_calls[0]["segments"]
    ] == [23, 8]


def test_polish_budget_looks_ahead_across_chunk_boundary(tmp_path: Path) -> None:
    translator = _PolishTranslator(
        polish_responses=[
            [f"推敲{index}" for index in range(10)],
            ["推敲10"],
        ]
    )
    segments = [
        TranscriptSegment(
            id=index,
            start=float(index * 2),
            end=float(index * 2 + 1),
            text=f"Sentence {index}.",
        )
        for index in range(11)
    ]

    _run_pipeline(
        tmp_path,
        translator,
        segments=segments,
        translate_dedup_enabled=False,
    )

    assert translator.polish_calls[0]["segments"][-1]["targetChars"] == 16
    assert translator.polish_calls[1]["segments"][0]["targetChars"] == 8


def test_target_budget_config_defaults_env_validation_and_project_dir_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REVERB_TRANSLATE_TARGET_GAP_CAP_SECONDS", raising=False)
    monkeypatch.delenv("REVERB_TRANSLATE_TARGET_SPEED_FACTOR", raising=False)
    monkeypatch.setenv("REVERB_MIX_MAX_DRIFT_SECONDS", "3.0")
    defaults = BackendConfig()
    assert defaults.translate_target_gap_cap_seconds == 3.0
    assert defaults.translate_target_speed_factor == 1.3

    monkeypatch.setenv("REVERB_TRANSLATE_TARGET_GAP_CAP_SECONDS", "1.75")
    monkeypatch.setenv("REVERB_TRANSLATE_TARGET_SPEED_FACTOR", "1.2")
    config = BackendConfig()
    copied = config.with_projects_dir(tmp_path)

    assert copied.translate_target_gap_cap_seconds == 1.75
    assert copied.translate_target_speed_factor == 1.2
    with pytest.raises(ValueError):
        dataclasses.replace(config, translate_target_gap_cap_seconds=-0.1)
    with pytest.raises(ValueError):
        dataclasses.replace(config, translate_target_speed_factor=-0.1)
    with pytest.raises(ValueError):
        dataclasses.replace(config, translate_target_speed_factor=1.31)
