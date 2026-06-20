from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from core.config import BackendConfig
from core.errors import StageError
from core.job_store import JobRecord, JobStore
from pipeline.extract import ExtractStage
from pipeline.stub_stages import StubStage
from schemas.enums import JobState, StageName, StageState
from schemas.settings import default_job_settings
from services.pipeline_runner import PipelineRunner


class FakeFFmpegAdapter:
    def __init__(
        self,
        *,
        has_audio: bool = True,
        duration: float = 10.0,
        error: Optional[StageError] = None,
        progress_values: Optional[List[float]] = None,
    ) -> None:
        self.has_audio = has_audio
        self.duration = duration
        self.error = error
        self.progress_values = progress_values or [0.0, 0.25, 0.5, 1.0]

    def probe(self, video_path: str) -> tuple[bool, float]:
        return self.has_audio, self.duration

    def extract(
        self,
        video_path: str,
        out_path: Path,
        options: dict,
        progress_cb: Callable[[float], None],
    ) -> None:
        if self.error:
            raise self.error
        for progress in self.progress_values:
            progress_cb(progress)
        out_path.write_bytes(b"wav")


def test_extract_happy_path_records_artifact_duration_and_progress(tmp_path: Path) -> None:
    record, notifications = _run_pipeline(
        tmp_path,
        FakeFFmpegAdapter(progress_values=[0.0, 0.2, 0.6, 1.0]),
    )

    extract = record.stages[StageName.extract]
    assert record.status == JobState.done
    assert record.duration == 10.0
    assert extract.status == StageState.done
    assert extract.artifact == "audio.wav"
    assert (record.project_dir / "audio.wav").read_bytes() == b"wav"
    extract_progress = [
        snapshot.stages[0].progress
        for snapshot in notifications
        if snapshot.currentStage == "extract"
    ]
    assert extract_progress[0] == 0.0
    assert extract_progress[-1] == 1.0
    assert 0.2 in extract_progress
    assert 0.6 in extract_progress


def test_extract_fails_when_probe_finds_no_audio_track(tmp_path: Path) -> None:
    record, _ = _run_pipeline(tmp_path, FakeFFmpegAdapter(has_audio=False))

    assert record.status == JobState.failed
    assert record.error is not None
    assert record.error.code == "NO_AUDIO_TRACK"
    assert record.stages[StageName.extract].status == StageState.failed


def test_extract_failed_error_code_is_preserved(tmp_path: Path) -> None:
    record, _ = _run_pipeline(
        tmp_path,
        FakeFFmpegAdapter(error=StageError("EXTRACT_FAILED", "decode failed")),
    )

    assert record.status == JobState.failed
    assert record.error is not None
    assert record.error.code == "EXTRACT_FAILED"
    assert record.error.message == "decode failed"


def test_ffmpeg_unavailable_error_code_is_preserved(tmp_path: Path) -> None:
    record, _ = _run_pipeline(
        tmp_path,
        FakeFFmpegAdapter(error=StageError("FFMPEG_UNAVAILABLE", "ffmpeg not found")),
    )

    assert record.status == JobState.failed
    assert record.error is not None
    assert record.error.code == "FFMPEG_UNAVAILABLE"


def test_extract_progress_callback_notifies_intermediate_values(tmp_path: Path) -> None:
    record, notifications = _run_pipeline(
        tmp_path,
        FakeFFmpegAdapter(progress_values=[0.0, 0.1, 0.5, 0.9, 1.0]),
    )

    extract_progress = [
        snapshot.stages[0].progress
        for snapshot in notifications
        if snapshot.currentStage == "extract"
    ]
    assert record.status == JobState.done
    assert len(extract_progress) >= 5
    assert extract_progress[0] == 0.0
    assert extract_progress[-1] == 1.0
    assert any(0.0 < progress < 1.0 for progress in extract_progress)


def _run_pipeline(
    tmp_path: Path,
    adapter: FakeFFmpegAdapter,
) -> tuple[JobRecord, list]:
    config = BackendConfig().with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record = store.create("/tmp/input.mp4", default_job_settings(config))
    notifications = []
    runner = PipelineRunner(
        config,
        store,
        [
            ExtractStage(adapter),
            StubStage(StageName.transcribe, "transcript.json"),
            StubStage(StageName.translate, "translation.json"),
            StubStage(StageName.subtitle, "subtitles.json"),
            StubStage(StageName.tts, "tts/cue_0000.wav"),
            StubStage(StageName.mix, "voiceover.wav"),
        ],
        lambda job: notifications.append(job.snapshot()),
    )

    runner.run(record)
    return record, notifications
