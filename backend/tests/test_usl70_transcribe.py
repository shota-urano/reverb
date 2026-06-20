from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from core.artifacts import read_transcript
from core.config import BackendConfig
from core.errors import StageError
from core.job_store import JobRecord, JobStore
from pipeline.extract import ExtractStage
from pipeline.stub_stages import StubStage
from pipeline.transcribe import TranscribeStage
from schemas.enums import JobState, StageName, StageState
from schemas.settings import default_job_settings
from services.pipeline_runner import PipelineRunner


class FakeFFmpegAdapter:
    def __init__(self, *, duration: float = 10.0) -> None:
        self.duration = duration

    def probe(self, video_path: str) -> tuple[bool, float]:
        return True, self.duration

    def extract(
        self,
        video_path: str,
        out_path: Path,
        options: dict,
        progress_cb: Callable[[float], None],
    ) -> None:
        progress_cb(0.0)
        out_path.write_bytes(b"wav")
        progress_cb(1.0)


class FakeWhisperAdapter:
    def __init__(
        self,
        *,
        language_detected: Optional[str] = "en",
        segments: Optional[list[dict]] = None,
        error: Optional[StageError] = None,
    ) -> None:
        self.language_detected = language_detected
        self.segments = segments if segments is not None else []
        self.error = error
        self.calls = []

    def transcribe(
        self,
        audio_path: Path,
        model: str,
        language: Optional[str],
        options: dict,
        progress_cb: Callable[[float], None],
    ) -> tuple[Optional[str], list[dict]]:
        self.calls.append(
            {
                "audio_path": audio_path,
                "model": model,
                "language": language,
                "options": options,
            }
        )
        progress_cb(0.0)
        if self.error:
            raise self.error
        progress_cb(1.0)
        return self.language_detected, self.segments


def test_transcribe_happy_path_writes_transcript_artifact_and_progress(
    tmp_path: Path,
) -> None:
    whisper = FakeWhisperAdapter(
        language_detected="en",
        segments=[
            {"start": 0.0, "end": 1.5, "text": "  Hello.  "},
            {"start": 1.5, "end": 2.0, "text": "   "},
            {"start": 2.0, "end": 4.25, "text": "World."},
        ],
    )

    record, notifications = _run_pipeline(tmp_path, whisper)

    transcript = read_transcript(record.project_dir)
    assert record.status == JobState.done
    assert record.stages[StageName.transcribe].status == StageState.done
    assert record.stages[StageName.transcribe].artifact == "transcript.json"
    assert transcript.engine == "mlx-whisper"
    assert transcript.model == record.settings.stt.model
    assert transcript.language == "en"
    assert transcript.duration == 10.0
    assert [segment.id for segment in transcript.segments] == [0, 1]
    assert [segment.text for segment in transcript.segments] == ["Hello.", "World."]
    assert [(segment.start, segment.end) for segment in transcript.segments] == [
        (0.0, 1.5),
        (2.0, 4.25),
    ]
    assert whisper.calls[0]["audio_path"] == record.project_dir / "audio.wav"
    transcribe_progress = [
        snapshot.stages[1].progress
        for snapshot in notifications
        if snapshot.currentStage == "transcribe"
    ]
    assert transcribe_progress[0] == 0.0
    assert transcribe_progress[-1] == 1.0


def test_transcribe_all_silent_writes_empty_segments_without_error(tmp_path: Path) -> None:
    record, _ = _run_pipeline(tmp_path, FakeWhisperAdapter(language_detected="en", segments=[]))

    transcript = read_transcript(record.project_dir)
    assert record.status == JobState.done
    assert record.stages[StageName.transcribe].status == StageState.done
    assert transcript.segments == []


def test_transcribe_model_missing_error_code_is_preserved(tmp_path: Path) -> None:
    record, _ = _run_pipeline(
        tmp_path,
        FakeWhisperAdapter(
            error=StageError("STT_MODEL_MISSING", "Install the configured STT model")
        ),
    )

    assert record.status == JobState.failed
    assert record.error is not None
    assert record.error.code == "STT_MODEL_MISSING"
    assert record.stages[StageName.transcribe].status == StageState.failed


def test_transcribe_failed_error_code_is_preserved(tmp_path: Path) -> None:
    record, _ = _run_pipeline(
        tmp_path,
        FakeWhisperAdapter(error=StageError("STT_FAILED", "inference failed")),
    )

    assert record.status == JobState.failed
    assert record.error is not None
    assert record.error.code == "STT_FAILED"
    assert record.error.message == "inference failed"
    assert record.stages[StageName.transcribe].status == StageState.failed


def _run_pipeline(
    tmp_path: Path,
    whisper: FakeWhisperAdapter,
) -> tuple[JobRecord, list]:
    config = BackendConfig().with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record = store.create("/tmp/input.mp4", default_job_settings(config))
    notifications = []
    runner = PipelineRunner(
        config,
        store,
        [
            ExtractStage(FakeFFmpegAdapter()),
            TranscribeStage(whisper),
            StubStage(StageName.translate, "translation.json"),
            StubStage(StageName.subtitle, "subtitles.json"),
            StubStage(StageName.tts, "tts/cue_0000.wav"),
            StubStage(StageName.mix, "voiceover.wav"),
        ],
        lambda job: notifications.append(job.snapshot()),
    )

    runner.run(record)
    return record, notifications
