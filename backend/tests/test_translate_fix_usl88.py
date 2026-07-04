from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Optional

import pytest

from adapters.ollama import OllamaAdapter
from core.config import BackendConfig
from pipeline.translate import TranslateStage
from schemas.artifacts import TranscriptSegment


class FakeTranslator:
    def __init__(self, responses: list[list[str]]) -> None:
        self.responses = responses
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
        return self.responses.pop(0)

    def polish(self, segments, model, system_prompt, temperature):
        return [segment["text"] for segment in segments]


def test_parser_maps_object_array_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter_with_content(
        monkeypatch,
        json.dumps(
            [
                {"id": 2, "text": "二番目です。"},
                {"id": 1, "text": "一番目です。"},
            ],
            ensure_ascii=False,
        ),
    )

    translated = adapter.translate(
        _input_segments(),
        "qwen3",
        "en",
        "system prompt",
        2,
    )

    assert translated == ["一番目です。", "二番目です。"]


def test_parser_handles_string_array_positionally(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter_with_content(
        monkeypatch,
        json.dumps(["一番目です。", "二番目です。"], ensure_ascii=False),
    )

    translated = adapter.translate(
        _input_segments(),
        "qwen3",
        "en",
        "system prompt",
        2,
    )

    assert translated == ["一番目です。", "二番目です。"]


def test_parser_extracts_json_from_code_fence_and_surrounding_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter_with_content(
        monkeypatch,
        """
Here is the translation:
```json
[
  {"id": 1, "text": "一番目です。"},
  {"id": 2, "text": "二番目です。"}
]
```
Done.
""",
    )

    translated = adapter.translate(
        _input_segments(),
        "qwen3",
        "en",
        "system prompt",
        2,
    )

    assert translated == ["一番目です。", "二番目です。"]


def test_translate_chunk_retries_empty_targets_then_returns_success() -> None:
    translator = FakeTranslator(
        responses=[
            ["", ""],
            ["一番目です。", "二番目です。"],
        ]
    )
    stage = TranslateStage(translator)

    translated = stage._translate_chunk(
        _context(),
        _transcript_segments(),
        _transcript_segments(),
        "en",
        "qwen3",
    )

    assert translated == ["一番目です。", "二番目です。"]
    assert len(translator.calls) == 2


def test_translate_chunk_falls_back_to_source_after_empty_targets_exhaust_retries() -> None:
    # USL-97: 単発の非空原文に対し、リトライ後も空訳のままなら原文へフォールバックし
    # 工程を継続する（1セグメントで全体を落とさない）。過半が空の場合のみ失敗させる。
    translator = FakeTranslator(
        responses=[
            ["", "二番目です。"],
            ["", "二番目です。"],
        ]
    )
    stage = TranslateStage(translator)

    translated = stage._translate_chunk(
        _context(),
        _transcript_segments(),
        _transcript_segments(),
        "en",
        "qwen3",
    )

    assert translated == ["First.", "二番目です。"]
    assert len(translator.calls) == 2


def _adapter_with_content(monkeypatch: pytest.MonkeyPatch, content: str) -> OllamaAdapter:
    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)

    def post_json(*_: object) -> dict:
        return {"message": {"content": content}}

    monkeypatch.setattr(adapter, "_post_json", post_json)
    return adapter


def _input_segments() -> list[dict[str, object]]:
    return [
        {"id": 1, "text": "First."},
        {"id": 2, "text": "Second."},
    ]


def _transcript_segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(id=1, start=0.0, end=1.0, text="First."),
        TranscriptSegment(id=2, start=1.0, end=2.0, text="Second."),
    ]


def _context() -> SimpleNamespace:
    config = BackendConfig(
        translate_max_retries=1,
        translate_retry_initial_wait=0.0,
    )
    return SimpleNamespace(config=config)
