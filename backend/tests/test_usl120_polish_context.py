from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from adapters.ollama import OllamaAdapter
from core.artifacts import read_translation
from core.config import BackendConfig, DEFAULT_TRANSLATE_POLISH_SYSTEM_PROMPT
from schemas.artifacts import TranscriptSegment
from test_usl115_polish import _PolishTranslator, _run_pipeline


def test_polish_uses_confirmed_polished_segments_as_context(tmp_path: Path) -> None:
    translator = _PolishTranslator(
        polish_responses=[
            [f"推敲{segment_id}です。" for segment_id in range(10)],
            ["そのため、推敲10です。"],
        ]
    )
    segments = [
        TranscriptSegment(
            id=segment_id,
            start=float(segment_id * 3),
            end=float(segment_id * 3 + 1),
            text=f"Source {segment_id}.",
        )
        for segment_id in range(11)
    ]

    record = _run_pipeline(
        tmp_path,
        translator,
        segments=segments,
        translate_dedup_enabled=False,
        translate_polish_context_window=1,
    )

    assert translator.polish_calls[0]["segments"][0] == {
        "id": 0,
        "text": "直訳0",
        "targetChars": 23,
    }
    assert translator.polish_calls[1]["segments"] == [
        {
            "id": 9,
            "text": "Source 9.",
            "target": "推敲9です。",
            "targetChars": 23,
            "contextOnly": True,
        },
        {"id": 10, "text": "直訳10", "targetChars": 8},
    ]
    translation = read_translation(record.project_dir)
    assert [segment.id for segment in translation.segments] == list(range(11))
    assert [segment.target for segment in translation.segments] == [
        *[f"推敲{segment_id}です。" for segment_id in range(10)],
        "そのため、推敲10です。",
    ]


def test_polish_context_window_zero_sends_legacy_segments_only(tmp_path: Path) -> None:
    translator = _PolishTranslator(
        polish_responses=[
            [f"推敲{segment_id}です。" for segment_id in range(10)],
            ["推敲10です。"],
        ]
    )
    segments = [
        TranscriptSegment(
            id=segment_id,
            start=float(segment_id * 3),
            end=float(segment_id * 3 + 1),
            text=f"Source {segment_id}.",
        )
        for segment_id in range(11)
    ]

    _run_pipeline(
        tmp_path,
        translator,
        segments=segments,
        translate_dedup_enabled=False,
        translate_polish_context_window=0,
    )

    assert translator.polish_calls[1]["segments"] == [
        {"id": 10, "text": "直訳10", "targetChars": 8}
    ]


def test_ollama_polish_sends_context_but_validates_only_input_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)
    captured_payload: dict = {}

    def post_json(_: str, payload: dict, __: str) -> dict:
        captured_payload.update(payload)
        return {"message": {"content": '[{"id": 2, "text": "第二推敲です。"}]'}}

    monkeypatch.setattr(adapter, "_post_json", post_json)
    segments = [
        {
            "id": 1,
            "text": "First source.",
            "target": "第一推敲です。",
            "targetChars": 16,
            "contextOnly": True,
        },
        {"id": 2, "text": "直訳2", "targetChars": 8},
    ]

    result = adapter.polish(segments, "polish-model", "polish prompt", 0.25)

    assert result == ["第二推敲です。"]
    assert json.loads(captured_payload["messages"][1]["content"]) == {
        "contextSegments": [{"id": 1, "source": "First source.", "target": "第一推敲です。"}],
        "inputSegments": [{"id": 2, "text": "直訳2", "targetChars": 8}],
    }


def test_ollama_polish_without_context_keeps_legacy_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)
    captured_payload: dict = {}

    def post_json(_: str, payload: dict, __: str) -> dict:
        captured_payload.update(payload)
        return {"message": {"content": '[{"id": 2, "text": "第二推敲です。"}]'}}

    monkeypatch.setattr(adapter, "_post_json", post_json)
    segments = [{"id": 2, "text": "直訳2", "targetChars": 8}]

    adapter.polish(segments, "polish-model", "polish prompt", 0.25)

    assert captured_payload["messages"][1]["content"] == json.dumps(
        segments,
        ensure_ascii=False,
    )


def test_polish_context_window_config_env_validation_and_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REVERB_TRANSLATE_POLISH_CONTEXT_WINDOW", raising=False)
    assert BackendConfig().translate_polish_context_window > 0

    monkeypatch.setenv("REVERB_TRANSLATE_POLISH_CONTEXT_WINDOW", "3")
    config = BackendConfig()

    assert config.translate_polish_context_window == 3
    assert config.with_projects_dir(tmp_path).translate_polish_context_window == 3
    with pytest.raises(ValueError):
        dataclasses.replace(config, translate_polish_context_window=-1)


def test_default_polish_prompt_describes_context_and_narration_style() -> None:
    assert "落ち着いた「です・ます」調" in DEFAULT_TRANSLATE_POLISH_SYSTEM_PROMPT
    assert "接続表現・指示語" in DEFAULT_TRANSLATE_POLISH_SYSTEM_PROMPT
    assert "読点" in DEFAULT_TRANSLATE_POLISH_SYSTEM_PROMPT
    assert "contextSegments" in DEFAULT_TRANSLATE_POLISH_SYSTEM_PROMPT
    assert "出力してはいけません" in DEFAULT_TRANSLATE_POLISH_SYSTEM_PROMPT
