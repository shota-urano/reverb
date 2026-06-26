from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from adapters.ollama import OllamaAdapter
from core.errors import StageError


def test_translate_extracts_text_from_translation_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter_with_translation_content(
        monkeypatch,
        [{"id": 0, "text": "Hello"}, {"id": 1, "text": "World"}],
    )

    translated = adapter.translate(
        _translation_segments(),
        "qwen3",
        "en",
        "system prompt",
        2,
    )

    assert translated == ["Hello", "World"]


def test_translate_orders_translation_objects_by_input_segment_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter_with_translation_content(
        monkeypatch,
        [{"id": 1, "text": "World"}, {"id": 0, "text": "Hello"}],
    )

    translated = adapter.translate(
        _translation_segments(),
        "qwen3",
        "en",
        "system prompt",
        2,
    )

    assert translated == ["Hello", "World"]


def test_translate_returns_empty_string_for_non_dict_element(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter_with_translation_content(
        monkeypatch,
        [{"id": 0, "text": "Hello"}, "not a dict"],
    )

    translated = adapter.translate(
        _translation_segments(),
        "qwen3",
        "en",
        "system prompt",
        2,
    )

    assert translated == ["Hello", ""]


def test_translate_returns_empty_string_for_missing_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter_with_translation_content(
        monkeypatch,
        [{"id": 0, "text": "Hello"}, {"id": 1}],
    )

    translated = adapter.translate(
        _translation_segments(),
        "qwen3",
        "en",
        "system prompt",
        2,
    )

    assert translated == ["Hello", ""]


def test_translate_falls_back_to_positional_order_when_ids_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter_with_translation_content(
        monkeypatch,
        [{"text": "Hello"}, {"text": "World"}],
    )

    translated = adapter.translate(
        _translation_segments(),
        "qwen3",
        "en",
        "system prompt",
        2,
    )

    assert translated == ["Hello", "World"]


def test_translate_returns_placeholders_when_response_ids_do_not_match_input_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter_with_translation_content(
        monkeypatch,
        [{"id": 10, "text": "Hello"}, {"id": 11, "text": "World"}],
    )

    translated = adapter.translate(
        _translation_segments(),
        "qwen3",
        "en",
        "system prompt",
        2,
    )

    assert translated == ["", ""]


def test_translate_accepts_bare_object_for_single_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 文単位翻訳では inputSegments が1件になり、モデルが配列ではなく
    # 裸のオブジェクトを返すことがある。1要素として受理する。
    adapter = _adapter_with_raw_content(
        monkeypatch,
        '{"id": 15, "text": "自然な日本語の一文。"}',
    )

    translated = adapter.translate(
        [{"id": 15, "text": "a full english sentence."}],
        "qwen3",
        "en",
        "system prompt",
        2,
    )

    assert translated == ["自然な日本語の一文。"]


def test_translate_extracts_object_buried_in_thinking_preamble(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter_with_raw_content(
        monkeypatch,
        '<think>let me translate this</think>\n{"id": 15, "text": "自然な訳。"}',
    )

    translated = adapter.translate(
        [{"id": 15, "text": "a full english sentence."}],
        "qwen3",
        "en",
        "system prompt",
        2,
    )

    assert translated == ["自然な訳。"]


def test_translate_includes_keep_alive_in_chat_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_payload = {}
    adapter = OllamaAdapter(
        "http://127.0.0.1:11434",
        timeout_seconds=1,
        keep_alive="3600s",
    )

    def post_json(_: str, payload: dict, __: str) -> dict:
        captured_payload.update(payload)
        return {"message": {"content": json.dumps([{"id": 0, "text": "Hello"}])}}

    monkeypatch.setattr(adapter, "_post_json", post_json)

    translated = adapter.translate(
        [{"id": 0, "text": "Hello"}],
        "qwen3",
        "en",
        "system prompt",
        2,
    )

    assert translated == ["Hello"]
    assert captured_payload["keep_alive"] == "3600s"


def test_post_json_404_not_found_raises_model_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _raise_error(_http_error(404, b"model qwen3 not found")),
    )

    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)

    with pytest.raises(StageError) as exc_info:
        adapter._post_json("/api/chat", {"model": "qwen3"}, "qwen3")

    assert exc_info.value.code == "MODEL_MISSING"


def test_post_json_500_model_load_failed_raises_retryable_ollama_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _raise_error(_http_error(500, b"model load failed")),
    )

    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)

    with pytest.raises(StageError) as exc_info:
        adapter._post_json("/api/chat", {"model": "qwen3"}, "qwen3")

    assert exc_info.value.code == "OLLAMA_UNAVAILABLE"
    assert exc_info.value.retryable is True


def test_post_json_url_error_raises_retryable_ollama_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _raise_error(urllib.error.URLError("connection refused")),
    )

    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)

    with pytest.raises(StageError) as exc_info:
        adapter._post_json("/api/chat", {"model": "qwen3"}, "qwen3")

    assert exc_info.value.code == "OLLAMA_UNAVAILABLE"
    assert exc_info.value.retryable is True


def _http_error(code: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://127.0.0.1:11434/api/chat",
        code=code,
        msg="error",
        hdrs=None,
        fp=io.BytesIO(body),
    )


def _raise_error(exc: BaseException):
    def raise_error(*_: object, **__: object) -> None:
        raise exc

    return raise_error


def _adapter_with_translation_content(
    monkeypatch: pytest.MonkeyPatch,
    translation: list[object],
) -> OllamaAdapter:
    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)

    def post_json(*_: object) -> dict:
        return {"message": {"content": json.dumps(translation)}}

    monkeypatch.setattr(adapter, "_post_json", post_json)
    return adapter


def _adapter_with_raw_content(
    monkeypatch: pytest.MonkeyPatch,
    content: str,
) -> OllamaAdapter:
    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)

    def post_json(*_: object) -> dict:
        return {"message": {"content": content}}

    monkeypatch.setattr(adapter, "_post_json", post_json)
    return adapter


def _translation_segments() -> list[dict[str, object]]:
    return [
        {"id": 0, "text": "Hello"},
        {"id": 1, "text": "World"},
    ]
