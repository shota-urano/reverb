from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from adapters.whisper_mlx import WhisperMLXAdapter


def test_transcribe_reports_smooth_monotonic_estimated_progress(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")
    progress_values: list[float] = []

    def fake_transcribe(
        audio: str,
        *,
        path_or_hf_repo: str,
        language: str | None,
    ) -> dict:
        assert audio == str(audio_path)
        assert path_or_hf_repo == str(model_dir)
        assert language == "en"

        deadline = time.monotonic() + 1.0
        while _intermediate_values(progress_values) < 2 and time.monotonic() < deadline:
            time.sleep(0.001)

        return {
            "language": "en",
            "segments": [{"start": 0.0, "end": 1.0, "text": "hello"}],
        }

    monkeypatch.setitem(
        __import__("sys").modules,
        "mlx_whisper",
        SimpleNamespace(transcribe=fake_transcribe),
    )

    adapter = WhisperMLXAdapter(
        {"large-v3": str(model_dir)},
        progress_rtf_estimate=0.05,
        progress_max_fraction=0.95,
        progress_interval_seconds=0.005,
    )

    language, segments = adapter.transcribe(
        audio_path,
        "large-v3",
        "en",
        {"duration": 1.0},
        progress_values.append,
    )

    assert language == "en"
    assert segments == [{"start": 0.0, "end": 1.0, "text": "hello"}]
    assert _intermediate_values(progress_values) >= 1
    assert progress_values == sorted(progress_values)
    assert all(0.0 <= value <= 1.0 for value in progress_values)
    assert progress_values[-1] == 1.0


def _intermediate_values(values: list[float]) -> int:
    return sum(1 for value in values if 0.0 < value < 1.0)
