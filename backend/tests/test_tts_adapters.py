from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from adapters.factory import build_tts_adapter
from adapters.voicevox_compatible import AivisSpeechAdapter, VoicevoxAdapter
from core.config import BackendConfig
from core.errors import StageError


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body

    def close(self) -> None:
        return None


def test_aivisspeech_synthesize_overwrites_speed_scale_and_preserves_intonation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[urllib.request.Request] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> FakeResponse:
        requests.append(request)
        if request.full_url.endswith("/audio_query?text=%E3%83%86%E3%82%B9%E3%83%88&speaker=7"):
            return FakeResponse(
                json.dumps(
                    {
                        "speedScale": 0.95,
                        "intonationScale": 0.72,
                        "accent_phrases": [],
                    }
                ).encode("utf-8")
            )
        if request.full_url.endswith("/synthesis?speaker=7"):
            assert timeout == 30.0
            return FakeResponse(b"wav-bytes")
        raise AssertionError(f"unexpected request: {request.full_url}")

    monkeypatch.setattr("adapters.voicevox_compatible.urllib.request.urlopen", fake_urlopen)

    adapter = AivisSpeechAdapter(
        "http://127.0.0.1:10101",
        timeout_seconds=0.5,
        synthesis_timeout_seconds=30.0,
    )

    assert adapter.synthesize("テスト", speaker_id=99, style_id=7, speed_scale=1.23) == b"wav-bytes"

    body = json.loads(requests[1].data.decode("utf-8"))  # type: ignore[union-attr]
    assert body["speedScale"] == 1.23
    assert body["intonationScale"] == 0.72


def test_aivisspeech_ping_and_list_speakers(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float) -> FakeResponse:
        assert timeout == 0.5
        if request.full_url.endswith("/version"):
            return FakeResponse(b'"0.0.1"')
        if request.full_url.endswith("/speakers"):
            return FakeResponse(
                json.dumps(
                    [
                        {
                            "name": "Calm Voice",
                            "styles": [
                                {"id": 101, "name": "Normal"},
                                {"id": "invalid", "name": "Invalid"},
                            ],
                        },
                        {"name": 1, "styles": []},
                    ]
                ).encode("utf-8")
            )
        raise AssertionError(f"unexpected request: {request.full_url}")

    monkeypatch.setattr("adapters.voicevox_compatible.urllib.request.urlopen", fake_urlopen)
    adapter = AivisSpeechAdapter("http://localhost:10101", 0.5, 30.0)

    assert adapter.ping() is True
    assert [speaker.model_dump() for speaker in adapter.list_speakers()] == [
        {"speakerId": 101, "name": "Calm Voice", "styleId": 101}
    ]


def test_aivisspeech_connection_errors_are_tts_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(*_: Any, **__: Any) -> None:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("adapters.voicevox_compatible.urllib.request.urlopen", fake_urlopen)
    adapter = AivisSpeechAdapter("http://127.0.0.1:10101", 0.5, 30.0)

    with pytest.raises(StageError) as exc_info:
        adapter.synthesize("テスト", speaker_id=1, style_id=1)

    assert exc_info.value.code == "TTS_UNAVAILABLE"
    assert exc_info.value.retryable is True


def test_aivisspeech_http_speaker_errors_are_speaker_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(*_: Any, **__: Any) -> None:
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:10101/audio_query",
            code=422,
            msg="Unprocessable Entity",
            hdrs=None,
            fp=FakeResponse(b"speaker not found"),
        )

    monkeypatch.setattr("adapters.voicevox_compatible.urllib.request.urlopen", fake_urlopen)
    adapter = AivisSpeechAdapter("http://127.0.0.1:10101", 0.5, 30.0)

    with pytest.raises(StageError) as exc_info:
        adapter.synthesize("テスト", speaker_id=1000, style_id=1000)

    assert exc_info.value.code == "SPEAKER_INVALID"
    assert "speaker not found" in exc_info.value.message


def test_tts_factory_selects_configured_engine() -> None:
    aivis = build_tts_adapter(
        BackendConfig(default_tts_engine="aivisspeech", aivisspeech_base_url="http://127.0.0.1:10101")
    )
    voicevox = build_tts_adapter(
        BackendConfig(default_tts_engine="voicevox", voicevox_base_url="http://127.0.0.1:50021")
    )

    assert isinstance(aivis, AivisSpeechAdapter)
    assert isinstance(voicevox, VoicevoxAdapter)
