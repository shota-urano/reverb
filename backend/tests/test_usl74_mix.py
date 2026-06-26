from __future__ import annotations

import io
import logging
import wave
from pathlib import Path
from typing import Optional

import pytest

from core.artifacts import (
    AUDIO_PATH,
    VOICEOVER_PATH,
    get_cue_wav_path,
    read_subtitles,
    write_subtitles,
)
from core.config import BackendConfig
from core.errors import StageError
from core.job_store import JobRecord, JobStore
from pipeline.mix import MixStage
from pipeline.stage import PipelineContext
from schemas.artifacts import SubtitleCue, Subtitles
from schemas.enums import JobState, StageName, StageState
from schemas.settings import default_job_settings
from services.job_service import build_pipeline_stages
from services.pipeline_runner import PipelineRunner


class FakeMixer:
    def __init__(self, error: Optional[StageError] = None) -> None:
        self.error = error
        self.calls: list[dict] = []

    def mix_voiceover(
        self,
        original_audio_path: Path,
        cue_inputs: list[tuple[Path, float]],
        out_path: Path,
        duration: float,
        ja_volume: float,
        original_volume: float,
    ) -> None:
        self.calls.append(
            {
                "original_audio_path": original_audio_path,
                "cue_inputs": cue_inputs,
                "out_path": out_path,
                "duration": duration,
                "ja_volume": ja_volume,
                "original_volume": original_volume,
            }
        )
        if self.error:
            raise self.error
        out_path.write_bytes(b"voiceover")


class FakeVoicevox:
    def __init__(
        self,
        *,
        responses: Optional[list[bytes]] = None,
        errors: Optional[dict[str, list[StageError]]] = None,
    ) -> None:
        self.responses = responses if responses is not None else []
        self.errors = errors if errors is not None else {}
        self.calls: list[dict] = []

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
        return _wav_bytes(1.0)


def test_mix_places_cues_from_start_times_outputs_voiceover_and_reports_progress(
    tmp_path: Path,
) -> None:
    mixer = FakeMixer()
    voicevox = FakeVoicevox()

    record, notifications = _run_pipeline(
        tmp_path,
        mixer,
        voicevox,
        duration=5.0,
        cues=[
            SubtitleCue(id=0, start=0.0, end=1.0, lines=["最初です。"], segmentIds=[0]),
            SubtitleCue(id=1, start=2.0, end=3.0, lines=["次です。"], segmentIds=[1]),
        ],
        cue_durations={0: 1.0, 1: 1.0},
    )

    assert record.status == JobState.done
    assert record.stages[StageName.mix].status == StageState.done
    assert record.stages[StageName.mix].artifact == str(VOICEOVER_PATH)
    assert (record.project_dir / VOICEOVER_PATH).read_bytes() == b"voiceover"
    assert mixer.calls == [
        {
            "original_audio_path": record.project_dir / AUDIO_PATH,
            "cue_inputs": [
                (get_cue_wav_path(record.project_dir, 0), 0.0),
                (get_cue_wav_path(record.project_dir, 1), 2.0),
            ],
            "out_path": record.project_dir / VOICEOVER_PATH,
            "duration": 5.0,
            "ja_volume": record.settings.mix.jaVolume,
            "original_volume": record.settings.mix.originalVolume,
        }
    ]
    mix_progress = [
        snapshot.stages[5].progress for snapshot in notifications if snapshot.currentStage == "mix"
    ]
    assert mix_progress[0] == 0.0
    assert mix_progress[-1] == 1.0


def test_mix_clamps_speed_scale_resynthesizes_and_passes_configured_volumes(
    tmp_path: Path,
) -> None:
    mixer = FakeMixer()
    voicevox = FakeVoicevox(responses=[_wav_bytes(1.3)])

    record, _ = _run_pipeline(
        tmp_path,
        mixer,
        voicevox,
        duration=8.0,
        cues=[
            SubtitleCue(id=0, start=0.0, end=1.0, lines=["長い音声。"], segmentIds=[0]),
            SubtitleCue(id=1, start=0.5, end=2.5, lines=["短い音声。"], segmentIds=[1]),
        ],
        cue_durations={0: 2.0, 1: 1.0},
        config=BackendConfig(ja_volume=0.7, original_volume=0.12).with_projects_dir(tmp_path),
    )

    assert record.status == JobState.done
    assert voicevox.calls == [
        {
            "text": "長い音声。",
            "speaker_id": record.settings.tts.speakerId,
            "style_id": record.settings.tts.styleId,
            "speed_scale": 1.3,
        },
    ]
    assert mixer.calls[0]["cue_inputs"] == [
        (get_cue_wav_path(record.project_dir, 0), 0.0),
        (get_cue_wav_path(record.project_dir, 1), 1.3),
    ]
    assert mixer.calls[0]["ja_volume"] == 0.7
    assert mixer.calls[0]["original_volume"] == 0.12


def test_mix_keeps_shorter_than_target_cues_at_equal_speed_without_resynthesizing(
    tmp_path: Path,
    caplog,
) -> None:
    mixer = FakeMixer()
    voicevox = FakeVoicevox()

    with caplog.at_level(logging.INFO):
        record, _ = _run_pipeline(
            tmp_path,
            mixer,
            voicevox,
            duration=4.0,
            cues=[SubtitleCue(id=0, start=0.0, end=2.0, lines=["短い音声。"], segmentIds=[0])],
            cue_durations={0: 1.0},
        )

    assert record.status == JobState.done
    assert voicevox.calls == []
    assert mixer.calls[0]["cue_inputs"] == [(get_cue_wav_path(record.project_dir, 0), 0.0)]
    assert any(
        log_record.message == "cue speed_scale"
        and log_record.cue_id == 0
        and log_record.speed_scale == 1.0
        for log_record in caplog.records
    )


def test_mix_missing_cue_warns_and_continues(tmp_path: Path, caplog) -> None:
    mixer = FakeMixer()
    voicevox = FakeVoicevox()

    with caplog.at_level(logging.WARNING):
        record, _ = _run_pipeline(
            tmp_path,
            mixer,
            voicevox,
            duration=4.0,
            cues=[
                SubtitleCue(id=0, start=0.0, end=1.0, lines=["欠落。"], segmentIds=[0]),
                SubtitleCue(id=1, start=1.5, end=2.5, lines=["続き。"], segmentIds=[1]),
            ],
            cue_durations={1: 1.0},
        )

    assert record.status == JobState.done
    assert record.stages[StageName.mix].status == StageState.done
    assert mixer.calls[0]["cue_inputs"] == [(get_cue_wav_path(record.project_dir, 1), 1.5)]
    assert "missing or empty TTS cue" in caplog.text


def test_mix_ffmpeg_failure_fails_job_with_mix_failed(tmp_path: Path) -> None:
    mixer = FakeMixer(error=StageError("MIX_FAILED", "ffmpeg stderr"))
    voicevox = FakeVoicevox()

    record, _ = _run_pipeline(
        tmp_path,
        mixer,
        voicevox,
        duration=2.0,
        cues=[SubtitleCue(id=0, start=0.0, end=1.0, lines=["失敗。"], segmentIds=[0])],
        cue_durations={0: 1.0},
    )

    assert record.status == JobState.failed
    assert record.error is not None
    assert record.error.code == "MIX_FAILED"
    assert record.error.message == "ffmpeg stderr"
    assert record.stages[StageName.mix].status == StageState.failed


def test_mix_writes_audio_aligned_subtitle_times_with_drift(tmp_path: Path) -> None:
    # cue0 の音声(2.0s)はスロット(1.0s)を超え 1.3 へ圧縮されてもまだ長く、
    # cue1 を後ろへ押し出す（元 start 1.0 → 配置 1.3）。この実配置時刻を
    # audioStart/audioEnd として字幕に書き込む。
    mixer = FakeMixer()
    voicevox = FakeVoicevox(responses=[_wav_bytes(1.3)])

    record, _ = _run_pipeline(
        tmp_path,
        mixer,
        voicevox,
        duration=8.0,
        cues=[
            SubtitleCue(id=0, start=0.0, end=1.0, lines=["長い音声。"], segmentIds=[0]),
            SubtitleCue(id=1, start=1.0, end=2.0, lines=["次の音声。"], segmentIds=[1]),
        ],
        cue_durations={0: 2.0, 1: 1.0},
    )

    subtitles = read_subtitles(record.project_dir)
    # audioStart は mixer に渡した配置時刻と一致する。
    assert mixer.calls[0]["cue_inputs"] == [
        (get_cue_wav_path(record.project_dir, 0), pytest.approx(0.0)),
        (get_cue_wav_path(record.project_dir, 1), pytest.approx(1.3)),
    ]
    assert subtitles.cues[0].audioStart == pytest.approx(0.0)
    assert subtitles.cues[0].audioEnd == pytest.approx(1.3)  # 次cueの配置開始でクランプ
    assert subtitles.cues[1].audioStart == pytest.approx(1.3)
    # 末尾cueは実音声(2.3)より最低表示1.5秒(1.3+1.5=2.8)を確保。
    assert subtitles.cues[1].audioEnd == pytest.approx(2.8)
    # 元の start/end は不変。
    assert subtitles.cues[1].start == 1.0
    assert subtitles.cues[1].end == 2.0


def test_mix_audio_alignment_is_idempotent(tmp_path: Path) -> None:
    # 同じ project に mix を2回かけても audioStart/audioEnd は二重シフトしない
    # （placement は元 start から計算するため）。
    record, _ = _run_pipeline(
        tmp_path,
        FakeMixer(),
        FakeVoicevox(),
        duration=4.0,
        cues=[
            SubtitleCue(id=0, start=0.0, end=1.0, lines=["一。"], segmentIds=[0]),
            SubtitleCue(id=1, start=1.0, end=2.0, lines=["二。"], segmentIds=[1]),
        ],
        cue_durations={0: 1.0, 1: 1.0},
    )
    first = read_subtitles(record.project_dir)

    config = BackendConfig().with_projects_dir(tmp_path)
    context = PipelineContext(config=config, job=record, project_dir=record.project_dir)
    MixStage(FakeMixer(), FakeVoicevox()).run(context)
    second = read_subtitles(record.project_dir)

    assert first == second
    assert first.cues[0].audioStart == pytest.approx(0.0)
    assert first.cues[1].audioStart == pytest.approx(1.0)


def test_mix_leaves_audio_times_none_for_missing_cue(tmp_path: Path) -> None:
    # TTS 欠落 cue は audioStart/audioEnd を None に保ち、プレーヤーは元時刻へフォールバック。
    record, _ = _run_pipeline(
        tmp_path,
        FakeMixer(),
        FakeVoicevox(),
        duration=4.0,
        cues=[
            SubtitleCue(id=0, start=0.0, end=1.0, lines=["欠落。"], segmentIds=[0]),
            SubtitleCue(id=1, start=1.5, end=2.5, lines=["続き。"], segmentIds=[1]),
        ],
        cue_durations={1: 1.0},
    )

    subtitles = read_subtitles(record.project_dir)
    assert subtitles.cues[0].audioStart is None
    assert subtitles.cues[0].audioEnd is None
    assert subtitles.cues[1].audioStart == pytest.approx(1.5)


def test_build_pipeline_stages_uses_real_mix_stage() -> None:
    stages = build_pipeline_stages(
        FakeMixer(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        FakeVoicevox(),
    )

    assert isinstance(stages[-1], MixStage)


def _run_pipeline(
    tmp_path: Path,
    mixer: FakeMixer,
    voicevox: FakeVoicevox,
    *,
    duration: float,
    cues: list[SubtitleCue],
    cue_durations: dict[int, float],
    config: Optional[BackendConfig] = None,
) -> tuple[JobRecord, list]:
    config = config or BackendConfig().with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record = store.create(str(tmp_path / "input.mp4"), default_job_settings(config))
    record.duration = duration
    (record.project_dir / AUDIO_PATH).write_bytes(_wav_bytes(duration))
    write_subtitles(record.project_dir, Subtitles(cues=cues))
    for cue_id, cue_duration in cue_durations.items():
        cue_path = get_cue_wav_path(record.project_dir, cue_id)
        cue_path.parent.mkdir(parents=True, exist_ok=True)
        cue_path.write_bytes(_wav_bytes(cue_duration))

    notifications = []
    runner = PipelineRunner(
        config,
        store,
        [MixStage(mixer, voicevox)],
        lambda job: notifications.append(job.snapshot()),
    )

    runner.run(record)
    return record, notifications


def _wav_bytes(duration: float, sample_rate: int = 24_000) -> bytes:
    buffer = io.BytesIO()
    frame_count = int(duration * sample_rate)
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00" * frame_count * 2)
    return buffer.getvalue()
