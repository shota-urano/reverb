from __future__ import annotations

import wave
from pathlib import Path
from typing import Optional

from core.artifacts import TTS_DIR, get_cue_wav_path, write_subtitles
from core.config import BackendConfig
from core.errors import StageError
from core.job_store import JobRecord, JobStore
from pipeline.stub_stages import StubStage
from pipeline.tts import TtsStage
from schemas.artifacts import SubtitleCue, Subtitles
from schemas.enums import JobState, StageName, StageState
from schemas.settings import default_job_settings
from services.pipeline_runner import PipelineRunner


class FakeVoicevox:
    def __init__(
        self,
        *,
        responses: Optional[list[bytes]] = None,
        errors: Optional[dict[str, list[StageError]]] = None,
    ) -> None:
        self.responses = responses if responses is not None else []
        self.errors = errors if errors is not None else {}
        self.calls = []

    def synthesize(
        self,
        text: str,
        speaker_id: int,
        style_id: int,
        speed_scale: float = 1.0,
    ) -> bytes:
        self.calls.append(
            {
                "text": text,
                "speaker_id": speaker_id,
                "style_id": style_id,
                "speed_scale": speed_scale,
            }
        )
        if self.errors.get(text):
            raise self.errors[text].pop(0)
        if self.responses:
            return self.responses.pop(0)
        return _wav_bytes()


def test_tts_writes_wav_per_cue_and_reports_progress(tmp_path: Path) -> None:
    voicevox = FakeVoicevox(responses=[b"wav-0", b"wav-1"])

    record, notifications = _run_pipeline(
        tmp_path,
        voicevox,
        cues=[
            SubtitleCue(id=0, start=0.0, end=1.0, lines=["こんにちは。"], segmentIds=[0]),
            SubtitleCue(id=1, start=1.0, end=2.0, lines=["世界です。"], segmentIds=[1]),
        ],
    )

    assert record.status == JobState.done
    assert record.stages[StageName.tts].status == StageState.done
    assert record.stages[StageName.tts].artifact == str(TTS_DIR)
    assert get_cue_wav_path(record.project_dir, 0).read_bytes() == b"wav-0"
    assert get_cue_wav_path(record.project_dir, 1).read_bytes() == b"wav-1"
    assert voicevox.calls == [
        {
            "text": "こんにちは。",
            "speaker_id": record.settings.tts.speakerId,
            "style_id": record.settings.tts.styleId,
            "speed_scale": 1.0,
        },
        {
            "text": "世界です。",
            "speaker_id": record.settings.tts.speakerId,
            "style_id": record.settings.tts.styleId,
            "speed_scale": 1.0,
        },
    ]
    tts_progress = [
        snapshot.stages[4].progress for snapshot in notifications if snapshot.currentStage == "tts"
    ]
    assert tts_progress[0] == 0.0
    assert tts_progress[-1] == 1.0


def test_tts_empty_input_creates_directory_and_finishes(tmp_path: Path) -> None:
    voicevox = FakeVoicevox()

    record, _ = _run_pipeline(tmp_path, voicevox, cues=[])

    assert record.status == JobState.done
    assert record.stages[StageName.tts].status == StageState.done
    assert record.stages[StageName.tts].artifact == str(TTS_DIR)
    assert (record.project_dir / TTS_DIR).is_dir()
    assert voicevox.calls == []


def test_tts_cue_failure_after_retries_writes_silent_placeholder_and_continues(
    tmp_path: Path,
) -> None:
    error = StageError("TTS_SYNTHESIS_FAILED", "temporary failure", retryable=True)
    voicevox = FakeVoicevox(errors={"失敗します。": [error, error]})

    record, _ = _run_pipeline(
        tmp_path,
        voicevox,
        cues=[
            SubtitleCue(id=0, start=0.0, end=1.0, lines=["失敗します。"], segmentIds=[0]),
            SubtitleCue(id=1, start=1.0, end=2.0, lines=["続きです。"], segmentIds=[1]),
        ],
        cue_retry_count=1,
    )

    failed_cue_path = get_cue_wav_path(record.project_dir, 0)
    assert record.status == JobState.done
    assert record.stages[StageName.tts].status == StageState.done
    assert len(voicevox.calls) == 3
    with wave.open(str(failed_cue_path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 24000
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == 12000
    assert get_cue_wav_path(record.project_dir, 1).exists()


def test_tts_voicevox_unavailable_before_any_cue_fails_retryable(tmp_path: Path) -> None:
    voicevox = FakeVoicevox(
        errors={
            "こんにちは。": [
                StageError("VOICEVOX_UNAVAILABLE", "not running", retryable=True),
            ]
        }
    )

    record, _ = _run_pipeline(
        tmp_path,
        voicevox,
        cues=[
            SubtitleCue(id=0, start=0.0, end=1.0, lines=["こんにちは。"], segmentIds=[0]),
        ],
        cue_retry_count=0,
    )

    assert record.status == JobState.failed
    assert record.error is not None
    assert record.error.code == "VOICEVOX_UNAVAILABLE"
    assert record.error.retryable is True
    assert record.stages[StageName.tts].status == StageState.failed


def _run_pipeline(
    tmp_path: Path,
    voicevox: FakeVoicevox,
    *,
    cues: list[SubtitleCue],
    cue_retry_count: int = 1,
) -> tuple[JobRecord, list]:
    config = BackendConfig(tts_cue_retry_count=cue_retry_count).with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record = store.create("/tmp/input.mp4", default_job_settings(config))
    write_subtitles(record.project_dir, Subtitles(cues=cues))

    notifications = []
    runner = PipelineRunner(
        config,
        store,
        [
            TtsStage(voicevox),
            StubStage(StageName.mix, "voiceover.wav"),
        ],
        lambda job: notifications.append(job.snapshot()),
    )

    runner.run(record)
    return record, notifications


def _wav_bytes() -> bytes:
    return b"RIFF$\x00\x00\x00WAVEfmt "
