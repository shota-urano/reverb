from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

from adapters.ollama import OllamaAdapter
from core.artifacts import read_translation, write_transcript
from core.config import BackendConfig
from core.errors import StageError
from core.job_store import JobStore
from pipeline.stage import PipelineContext
from pipeline.translate import TranslateStage, _confirmed_context_segments
from schemas.artifacts import Transcript, TranscriptSegment, Translation, TranslationSegment
from schemas.settings import default_job_settings


class FakeTranslator:
    def __init__(
        self,
        responses: list[list[str]],
        errors: Optional[list[StageError]] = None,
    ) -> None:
        self.responses = responses
        self.errors = errors or []
        self.calls: list[list[dict[str, object]]] = []

    def generate_glossary(
        self, transcript: str, model: str, source_lang: Optional[str], max_terms: int
    ) -> list[dict[str, str]]:
        return []

    def warm_up(self, model: str, system_prompt: str) -> None:
        return None

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
        if self.errors:
            raise self.errors.pop(0)
        return self.responses.pop(0)

    def polish(self, segments, model, system_prompt, temperature):
        return [segment["text"] for segment in segments]


def test_translates_configured_number_of_sentence_groups_per_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # USL-110 テストはデデュープではなく翻訳グループのバッチ分割を検証するため無効化する。
    monkeypatch.setenv("REVERB_TRANSLATE_DEDUP_ENABLED", "false")
    translator = FakeTranslator(
        responses=[
            ["一。", "二。"],
            ["三。", "四。"],
            ["五。"],
        ]
    )

    translation = _run_translate(
        tmp_path,
        translator,
        [
            _segment(index, float(index * 3), float(index * 3 + 1), f"Sentence {index}.")
            for index in range(5)
        ],
        translate_chunk_groups=2,
    )

    assert [[item["id"] for item in _inputs(call)] for call in translator.calls] == [
        [0, 1],
        [2, 3],
        [4],
    ]
    assert [segment.target for segment in translation.segments] == [
        "一。",
        "二。",
        "三。",
        "四。",
        "五。",
    ]


def test_passes_previous_confirmed_source_target_pairs_as_context(tmp_path: Path) -> None:
    translator = FakeTranslator(responses=[["第一訳。", "第二訳。"], ["第三訳。"]])

    _run_translate(
        tmp_path,
        translator,
        [
            _segment(10, 0.0, 1.0, "First."),
            _segment(11, 3.0, 4.0, "Second."),
            _segment(12, 6.0, 7.0, "Third."),
        ],
        translate_chunk_groups=2,
    )

    assert _contexts(translator.calls[1]) == [
        {
            "id": 10,
            "start": 0.0,
            "end": 1.0,
            "text": "First.",
            "target": "第一訳。",
            "contextOnly": True,
        },
        {
            "id": 11,
            "start": 3.0,
            "end": 4.0,
            "text": "Second.",
            "target": "第二訳。",
            "contextOnly": True,
        },
    ]


def test_confirmed_context_segments_returns_empty_when_context_window_is_zero() -> None:
    confirmed_segments = [
        TranslationSegment(
            id=1,
            start=0.0,
            end=1.0,
            source="Previous.",
            target="直前の訳。",
        )
    ]

    assert _confirmed_context_segments(confirmed_segments, 0) == []


def test_adds_target_chars_from_speaking_duration(tmp_path: Path) -> None:
    translator = FakeTranslator(responses=[["訳。"]])

    _run_translate(
        tmp_path,
        translator,
        [_segment(3, 1.0, 3.5, "A sentence.")],
        translate_chars_per_sec=6.0,
    )

    assert _inputs(translator.calls[0])[0]["targetChars"] == 15


def test_retries_when_id_mapping_fails(tmp_path: Path) -> None:
    translator = FakeTranslator(
        responses=[["成功。"]],
        errors=[StageError("TRANSLATE_MISALIGN", "IDs did not match.", retryable=True)],
    )

    translation = _run_translate(
        tmp_path,
        translator,
        [_segment(1, 0.0, 1.0, "First.")],
        translate_max_retries=1,
    )

    assert len(translator.calls) == 2
    assert translation.segments[0].target == "成功。"


def test_batch_keeps_non_linguistic_and_falls_back_only_empty_target(tmp_path: Path) -> None:
    translator = FakeTranslator(responses=[["", "第二訳。"], ["", "第二訳。"]])

    translation = _run_translate(
        tmp_path,
        translator,
        [
            _segment(1, 0.0, 1.0, "First."),
            _segment(2, 1.0, 2.0, "!!!"),
            _segment(3, 2.0, 3.0, "Second."),
        ],
        translate_chunk_groups=3,
        translate_max_retries=1,
        translate_fallback_threshold=0.5,
    )

    assert [segment.target for segment in translation.segments] == ["First.", "!!!", "第二訳。"]
    assert [[item["id"] for item in _inputs(call)] for call in translator.calls] == [[1, 3], [1, 3]]


def test_ollama_payload_contains_confirmed_context_and_target_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)

    def post_json(_: str, payload: dict, __: str) -> dict:
        captured.update(payload)
        return {"message": {"content": '[{"id": 2, "text": "次の訳。"}]'}}

    monkeypatch.setattr(adapter, "_post_json", post_json)
    adapter.translate(
        [
            {
                "id": 1,
                "text": "Previous.",
                "target": "直前の訳。",
                "contextOnly": True,
            },
            {"id": 2, "text": "Next.", "targetChars": 12, "contextOnly": False},
        ],
        "local-model",
        "en",
        "system prompt",
        4,
    )

    messages = captured["messages"]
    assert isinstance(messages, list)
    user_payload = json.loads(messages[1]["content"])
    assert user_payload == {
        "sourceLanguage": "en",
        "contextWindow": 4,
        "contextSegments": [{"id": 1, "source": "Previous.", "target": "直前の訳。"}],
        "inputSegments": [{"id": 2, "text": "Next.", "targetChars": 12}],
        "glossary": [],
    }


def test_ollama_accepts_jsonl_object_lines_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # qwen3 等は複数セグメント入力に対し、配列でなく JSONL（1行1オブジェクト）で
    # 返すことがある（実機で全リトライがこの形式だった）。全オブジェクトを回収する。
    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)
    content = (
        '{"id": 1, "text": "一。"}\n' '{"id": 2, "text": "二。"}\n' '{"id": 3, "text": "三。"}'
    )
    monkeypatch.setattr(adapter, "_post_json", lambda *_: {"message": {"content": content}})

    translated = adapter.translate(
        [
            {"id": 1, "text": "One.", "targetChars": 6},
            {"id": 2, "text": "Two.", "targetChars": 6},
            {"id": 3, "text": "Three.", "targetChars": 6},
        ],
        "local-model",
        "en",
        "system prompt",
        4,
    )

    assert translated == ["一。", "二。", "三。"]


def test_ollama_maps_string_response_ids_to_numeric_input_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)
    content = '[{"id": "1", "text": "一。"}, {"id": "2", "text": "二。"}]'
    monkeypatch.setattr(adapter, "_post_json", lambda *_: {"message": {"content": content}})

    translated = adapter.translate(
        [
            {"id": 1, "text": "One.", "targetChars": 6},
            {"id": 2, "text": "Two.", "targetChars": 6},
        ],
        "local-model",
        "en",
        "system prompt",
        4,
    )

    assert translated == ["一。", "二。"]


def test_ollama_accepts_superset_response_with_context_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # contextSegments の id を復唱しても、入力 id が全て揃っていれば受理する。
    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)
    content = '[{"id": 1, "text": "文脈の復唱"}, {"id": 2, "text": "本命の訳。"}]'
    monkeypatch.setattr(adapter, "_post_json", lambda *_: {"message": {"content": content}})

    translated = adapter.translate(
        [
            {"id": 1, "text": "Previous.", "target": "直前の訳。", "contextOnly": True},
            {"id": 2, "text": "Next.", "targetChars": 12},
        ],
        "local-model",
        "en",
        "system prompt",
        4,
    )

    assert translated == ["本命の訳。"]


def test_ollama_raises_misalign_when_response_ids_cannot_be_mapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)
    monkeypatch.setattr(
        adapter,
        "_post_json",
        lambda *_: {"message": {"content": '[{"id": 999, "text": "wrong"}]'}},
    )

    with pytest.raises(StageError) as exc_info:
        adapter.translate(
            [{"id": 2, "text": "Next.", "targetChars": 12}],
            "local-model",
            "en",
            "system prompt",
            4,
        )

    assert exc_info.value.code == "TRANSLATE_MISALIGN"
    assert exc_info.value.retryable is True


def test_new_translate_settings_have_env_overridable_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REVERB_TRANSLATE_CHUNK_GROUPS", raising=False)
    monkeypatch.delenv("REVERB_TRANSLATE_CHARS_PER_SEC", raising=False)
    assert BackendConfig().translate_chunk_groups == 4
    assert BackendConfig().translate_chars_per_sec == 6.0

    monkeypatch.setenv("REVERB_TRANSLATE_CHUNK_GROUPS", "6")
    monkeypatch.setenv("REVERB_TRANSLATE_CHARS_PER_SEC", "7.5")
    config = BackendConfig()
    assert config.translate_chunk_groups == 6
    assert config.translate_chars_per_sec == 7.5


def _run_translate(
    tmp_path: Path,
    translator: FakeTranslator,
    segments: list[TranscriptSegment],
    **config_overrides: object,
) -> Translation:
    config = BackendConfig(
        translate_chunk_size=10,
        translate_retry_initial_wait=0.0,
        **config_overrides,
    ).with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record = store.create("/tmp/input.mp4", default_job_settings(config))
    write_transcript(
        record.project_dir,
        Transcript(
            engine=config.default_stt_engine,
            model=record.settings.stt.model,
            language="en",
            duration=segments[-1].end if segments else 0.0,
            segments=segments,
        ),
    )
    TranslateStage(translator).run(PipelineContext(config, record, record.project_dir))
    return read_translation(record.project_dir)


def _segment(segment_id: int, start: float, end: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(id=segment_id, start=start, end=end, text=text)


def _inputs(call: list[dict[str, object]]) -> list[dict[str, object]]:
    return [item for item in call if not item.get("contextOnly")]


def _contexts(call: list[dict[str, object]]) -> list[dict[str, object]]:
    return [item for item in call if item.get("contextOnly")]
