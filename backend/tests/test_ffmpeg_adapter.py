from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from adapters.ffmpeg import FFmpegAdapter, _parse_progress_time, _voiceover_filter_graph
from core.errors import StageError


def test_require_local_path_allows_absolute_and_file_paths() -> None:
    adapter = FFmpegAdapter()

    assert adapter._require_local_path("/Users/me/a.mp4") == "/Users/me/a.mp4"
    assert adapter._require_local_path("file:///Users/me/a.mp4") == "/Users/me/a.mp4"


@pytest.mark.parametrize("video_path", ["http://example.com/a.mp4", "ftp://example.com/a.mp4"])
def test_require_local_path_rejects_remote_urls(video_path: str) -> None:
    adapter = FFmpegAdapter()

    with pytest.raises(StageError) as exc_info:
        adapter._require_local_path(video_path)

    assert exc_info.value.code == "EXTRACT_FAILED"
    assert "local file paths only" in exc_info.value.message


def test_probe_treats_non_numeric_duration_as_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("adapters.ffmpeg.shutil.which", lambda _: "/mock/ffprobe")
    monkeypatch.setattr(
        "adapters.ffmpeg.subprocess.run",
        lambda *_, **__: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "streams": [{"codec_type": "audio"}],
                    "format": {"duration": "N/A"},
                }
            ),
            stderr="",
        ),
    )

    has_audio, duration = FFmpegAdapter().probe("/Users/me/a.mp4")

    assert has_audio is True
    assert duration == 0.0


def test_parse_progress_time_returns_none_for_non_numeric_value() -> None:
    assert _parse_progress_time("N/A") is None


def test_extract_skips_unparseable_progress_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("adapters.ffmpeg.shutil.which", lambda _: "/mock/ffmpeg")
    progress_values: List[float] = []

    class FakeProcess:
        def __init__(self, command: list, **_: object) -> None:
            self.stdout = io.StringIO("out_time=N/A\nout_time=00:00:05.000000\n")
            self.returncode = None
            Path(command[-1]).write_bytes(b"wav")
            self.killed = False

        def wait(self) -> int:
            self.returncode = 0
            return 0

        def kill(self) -> None:
            self.killed = True

    monkeypatch.setattr("adapters.ffmpeg.subprocess.Popen", FakeProcess)

    out_path = tmp_path / "audio.wav"
    FFmpegAdapter().extract(
        "/Users/me/a.mp4",
        out_path,
        {"duration": 10.0, "channels": 1, "sample_rate": 16000, "codec": "pcm_s16le"},
        progress_values.append,
    )

    assert out_path.read_bytes() == b"wav"
    assert progress_values == [0.0, 0.5, 1.0]


def test_voiceover_filter_graph_disables_amix_normalization() -> None:
    filter_graph = _voiceover_filter_graph([(Path("ja.wav"), 1.0)], 10.0, 1.0, 0.08)

    assert "normalize=0" in filter_graph
    assert "volume=0.08" in filter_graph
    assert "volume=1.0" in filter_graph


def test_mix_voiceover_command_sets_wav_muxer_before_output_path() -> None:
    out_path = Path("voiceover.wav.tmp")

    command = FFmpegAdapter()._mix_voiceover_command(
        Path("original.wav"),
        [(Path("ja.wav"), 1.0)],
        out_path,
        10.0,
        1.0,
        0.08,
    )

    output_index = command.index(str(out_path))
    assert command[output_index - 2 : output_index] == ["-f", "wav"]
