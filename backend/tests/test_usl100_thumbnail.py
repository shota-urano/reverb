from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Dict

import pytest
from fastapi.testclient import TestClient

from adapters.ffmpeg import FFmpegAdapter
from core.config import BackendConfig
from core.errors import StageError
from core.job_store import JobStore
from main import create_app
from pipeline.extract import ExtractStage
from pipeline.stage import PipelineContext
from schemas.settings import default_job_settings


def test_ffmpeg_extract_thumbnail_builds_command_and_writes_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("adapters.ffmpeg.shutil.which", lambda _: "/mock/ffmpeg")
    captured_command: list[str] = []

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        captured_command[:] = command
        Path(command[-1]).write_bytes(b"jpg")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("adapters.ffmpeg.subprocess.run", fake_run)
    out_path = tmp_path / "thumbnail.jpg"

    FFmpegAdapter(ffmpeg_bin="ffmpeg-test").extract_thumbnail(
        "/Users/me/input.mp4",
        out_path,
        offset_seconds=1.25,
        width=320,
    )

    assert captured_command == [
        "ffmpeg-test",
        "-ss",
        "1.25",
        "-i",
        "/Users/me/input.mp4",
        "-frames:v",
        "1",
        "-vf",
        "scale=320:-2",
        "-y",
        "-f",
        "image2",
        str(out_path.with_name("thumbnail.jpg.tmp")),
    ]
    assert out_path.read_bytes() == b"jpg"
    assert not out_path.with_name("thumbnail.jpg.tmp").exists()


def test_ffmpeg_extract_thumbnail_raises_thumbnail_failed_on_command_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("adapters.ffmpeg.shutil.which", lambda _: "/mock/ffmpeg")
    monkeypatch.setattr(
        "adapters.ffmpeg.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stderr="decode failed"),
    )

    with pytest.raises(StageError) as exc_info:
        FFmpegAdapter().extract_thumbnail("/Users/me/input.mp4", tmp_path / "thumbnail.jpg", 1.0, 320)

    assert exc_info.value.code == "THUMBNAIL_FAILED"
    assert exc_info.value.message == "decode failed"


def test_ffmpeg_extract_thumbnail_rejects_remote_url(tmp_path: Path) -> None:
    with pytest.raises(StageError) as exc_info:
        FFmpegAdapter().extract_thumbnail(
            "https://example.com/input.mp4",
            tmp_path / "thumbnail.jpg",
            1.0,
            320,
        )

    assert "local file paths only" in exc_info.value.message


def test_extract_stage_thumbnail_failure_is_non_fatal(tmp_path: Path) -> None:
    config = BackendConfig().with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record = store.create("/tmp/input.mp4", default_job_settings(config))
    adapter = ThumbnailFailingExtractor()

    result = ExtractStage(adapter).run(
        PipelineContext(
            config=config,
            job=record,
            project_dir=record.project_dir,
        )
    )

    assert result == "audio.wav"
    assert adapter.extract_called is True
    assert adapter.thumbnail_called is True
    assert (record.project_dir / "audio.wav").read_bytes() == b"wav"


def test_thumbnail_endpoint_returns_image_or_404(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    record = app.state.job_store.create("/tmp/input.mp4", default_job_settings(app.state.config))
    thumbnail_path = record.project_dir / "thumbnail.jpg"
    thumbnail_path.write_bytes(b"\xff\xd8jpg")
    client = TestClient(app)

    response = client.get(f"/jobs/{record.job_id}/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"\xff\xd8jpg"

    thumbnail_path.unlink()
    missing = client.get(f"/jobs/{record.job_id}/thumbnail")
    assert missing.status_code == 404


def test_create_job_generates_thumbnail_in_project_dir(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    app.state.ffmpeg.probe = lambda _: (True, 12.5)
    app.state.ffmpeg.extract = lambda _, out_path, _options, progress_cb: (
        progress_cb(1.0),
        Path(out_path).write_bytes(b"wav"),
    )
    app.state.ffmpeg.extract_thumbnail = lambda _video, out_path, _offset, _width: Path(
        out_path
    ).write_bytes(b"jpg")
    app.state.ffmpeg.mix_voiceover = (
        lambda _audio, _cue_inputs, out_path, _duration, _ja_volume, _original_volume: Path(
            out_path
        ).write_bytes(b"voiceover")
    )
    app.state.whisper.transcribe = lambda _audio, _model, language, _options, progress_cb: (
        progress_cb(1.0),
        (language, []),
    )[-1]
    client = TestClient(app)

    created = client.post("/jobs", json={"videoPath": "/tmp/input.mp4"}).json()
    record = app.state.job_store.get(created["jobId"])

    assert (record.project_dir / "thumbnail.jpg").read_bytes() == b"jpg"


def test_has_thumbnail_reflects_file_presence_in_status_and_summary(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    record = app.state.job_store.create("/tmp/input.mp4", default_job_settings(app.state.config))
    client = TestClient(app)

    assert client.get(f"/jobs/{record.job_id}").json()["hasThumbnail"] is False
    assert client.get("/jobs").json()["items"][0]["hasThumbnail"] is False

    (record.project_dir / "thumbnail.jpg").write_bytes(b"jpg")

    assert client.get(f"/jobs/{record.job_id}").json()["hasThumbnail"] is True
    assert client.get("/jobs").json()["items"][0]["hasThumbnail"] is True


def test_thumbnail_config_env_validation_and_projects_dir_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("REVERB_THUMBNAIL_OFFSET_SECONDS", "2.5")
    monkeypatch.setenv("REVERB_THUMBNAIL_WIDTH", "640")

    config = BackendConfig()
    copied = config.with_projects_dir(tmp_path)

    assert config.thumbnail_offset_seconds == 2.5
    assert config.thumbnail_width == 640
    assert copied.thumbnail_offset_seconds == 2.5
    assert copied.thumbnail_width == 640
    assert copied.projects_dir == tmp_path

    with pytest.raises(ValueError):
        BackendConfig(thumbnail_offset_seconds=-0.1)
    with pytest.raises(ValueError):
        BackendConfig(thumbnail_width=0)


class ThumbnailFailingExtractor:
    def __init__(self) -> None:
        self.extract_called = False
        self.thumbnail_called = False

    def probe(self, video_path: str) -> tuple[bool, float]:
        return True, 12.0

    def extract(
        self,
        video_path: str,
        out_path: Path,
        options: Dict[str, object],
        progress_cb: Callable[[float], None],
    ) -> None:
        self.extract_called = True
        out_path.write_bytes(b"wav")
        progress_cb(1.0)

    def extract_thumbnail(
        self,
        video_path: str,
        out_path: Path,
        offset_seconds: float,
        width: int,
    ) -> None:
        self.thumbnail_called = True
        raise StageError("THUMBNAIL_FAILED", "thumbnail failed")
