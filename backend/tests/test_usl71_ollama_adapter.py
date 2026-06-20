from __future__ import annotations

import io
import urllib.error
import urllib.request

import pytest

from adapters.ollama import OllamaAdapter
from core.errors import StageError


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
