from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

import core.artifacts as artifacts
from core.artifacts import (
    AUDIO_PATH,
    read_subtitles,
    write_subtitles,
    write_translation,
)
from core.config import BackendConfig
from core.errors import StageError
from core.job_store import JobStore
from pipeline.mix import MixStage
from pipeline.stage import PipelineContext
from pipeline.tts import TtsStage
from schemas.artifacts import SubtitleCue, Subtitles, Translation, TranslationSegment
from schemas.settings import default_job_settings


class FakeSynthesizer:
    def __init__(self, duration: float = 1.0) -> None:
        self.duration = duration
        self.calls: list[dict[str, object]] = []

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
        return _wav_bytes(self.duration)


class FakeMixer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def mix_voiceover(
        self,
        original_audio_path: Path,
        clip_inputs: list[tuple[Path, float, float | None]],
        out_path: Path,
        duration: float,
        ja_volume: float,
        original_volume: float,
    ) -> None:
        self.calls.append(
            {
                "clip_inputs": clip_inputs,
                "duration": duration,
            }
        )
        out_path.write_bytes(b"voiceover")


def test_tts_synthesizes_one_wav_per_translation_segment_keyed_by_segment_id(
    tmp_path: Path,
) -> None:
    config, context = _context(tmp_path)
    write_translation(
        context.project_dir,
        _translation(
            _segment(7, 0.0, 2.0, "一文をまとめて読みます。"),
            _segment(11, 2.0, 4.0, "次の文です。"),
            _segment(15, 4.0, 5.0, "   "),
        ),
    )
    synthesizer = FakeSynthesizer()

    TtsStage(synthesizer).run(context)

    assert [call["text"] for call in synthesizer.calls] == [
        "一文をまとめて読みます。",
        "次の文です。",
    ]
    assert _segment_wav_path(context.project_dir, 7).exists()
    assert _segment_wav_path(context.project_dir, 11).exists()
    assert not _segment_wav_path(context.project_dir, 15).exists()
    assert config.projects_dir == tmp_path


def test_mix_caps_accumulated_drift_for_every_placed_segment(tmp_path: Path) -> None:
    _, context = _context(tmp_path, mix_max_drift_seconds=2.5, duration=12.0)
    segments = [
        _segment(0, 0.0, 1.0, "一。"),
        _segment(1, 1.0, 2.0, "二。"),
        _segment(2, 2.0, 3.0, "三。"),
    ]
    mixer = _prepare_mix(context, segments, wav_duration=3.0)

    MixStage(mixer, FakeSynthesizer(duration=3.0)).run(context)

    starts = [clip[1] for clip in mixer.calls[0]["clip_inputs"]]
    assert all(start - segment.start <= 2.5 for start, segment in zip(starts, segments))


def test_mix_trims_previous_clip_when_drift_cap_forces_overlap(tmp_path: Path) -> None:
    _, context = _context(tmp_path, mix_max_drift_seconds=2.5, duration=12.0)
    segments = [
        _segment(0, 0.0, 1.0, "一。"),
        _segment(1, 1.0, 2.0, "二。"),
        _segment(2, 2.0, 3.0, "三。"),
    ]
    mixer = _prepare_mix(context, segments, wav_duration=3.0)

    MixStage(mixer, FakeSynthesizer(duration=3.0)).run(context)

    clips = mixer.calls[0]["clip_inputs"]
    assert clips[1][1] == pytest.approx(3.0)
    assert clips[1][2] == pytest.approx(1.5)
    assert clips[1][1] + clips[1][2] == pytest.approx(clips[2][1])


def test_mix_apportions_one_segment_audio_across_multiple_cues(tmp_path: Path) -> None:
    _, context = _context(tmp_path, duration=6.0)
    segment = _segment(4, 0.0, 4.0, "あいうえ")
    mixer = _prepare_mix(
        context,
        [segment],
        wav_duration=4.0,
        cues=[
            SubtitleCue(id=0, start=0.0, end=1.0, lines=["あ"], segmentIds=[4]),
            SubtitleCue(id=1, start=1.0, end=4.0, lines=["いうえ"], segmentIds=[4]),
        ],
    )

    MixStage(mixer, FakeSynthesizer()).run(context)

    cues = read_subtitles(context.project_dir).cues
    assert cues[0].audioStart == pytest.approx(0.0)
    assert cues[0].audioEnd == pytest.approx(cues[1].audioStart)
    assert cues[1].audioEnd == pytest.approx(4.0)
    assert cues[1].audioEnd - cues[0].audioStart == pytest.approx(4.0)


def test_mix_fails_loudly_when_no_segment_audio_exists(tmp_path: Path) -> None:
    # 旧成果物スキーム（tts/cue_*.wav）のプロジェクトを途中再開した場合など、
    # 発話すべきセグメントがあるのに seg wav が皆無なら、日本語音声ゼロの
    # voiceover を黙って完成させず失敗させる。
    _, context = _context(tmp_path, duration=6.0)
    segments = [_segment(0, 0.0, 2.0, "一。"), _segment(1, 2.0, 4.0, "二。")]
    mixer = _prepare_mix(context, segments, wav_duration=1.0)
    for segment in segments:
        _segment_wav_path(context.project_dir, segment.id).unlink()

    with pytest.raises(StageError) as exc_info:
        MixStage(mixer, FakeSynthesizer()).run(context)

    assert exc_info.value.code == "MIX_INPUTS_MISSING"
    assert mixer.calls == []


def test_mix_completes_without_clips_when_translation_has_no_speakable_segment(
    tmp_path: Path,
) -> None:
    _, context = _context(tmp_path, duration=6.0)
    segments = [_segment(0, 0.0, 2.0, "   ")]
    mixer = _prepare_mix(context, segments, wav_duration=1.0)
    _segment_wav_path(context.project_dir, 0).unlink()

    MixStage(mixer, FakeSynthesizer()).run(context)

    assert mixer.calls[0]["clip_inputs"] == []


def test_mix_drops_fully_trimmed_clip_instead_of_passing_zero_length(
    tmp_path: Path,
) -> None:
    # 同一 start のセグメントが連続し前クリップが上限ちょうどに置かれると
    # トリム長が 0 になる。ゼロ長ストリームを ffmpeg に渡さないこと。
    _, context = _context(tmp_path, mix_max_drift_seconds=2.5, duration=30.0)
    segments = [
        _segment(0, 0.0, 1.0, "一。"),
        _segment(1, 0.0, 1.0, "二。"),
        _segment(2, 0.0, 1.0, "三。"),
    ]
    mixer = _prepare_mix(context, segments, wav_duration=10.0)

    MixStage(mixer, FakeSynthesizer(duration=10.0)).run(context)

    clips = mixer.calls[0]["clip_inputs"]
    assert len(clips) == 2
    assert clips[0][0] == _segment_wav_path(context.project_dir, 0)
    assert clips[0][2] == pytest.approx(2.5)
    assert clips[1][0] == _segment_wav_path(context.project_dir, 2)
    assert all(limit is None or limit > 0 for _, _, limit in clips)


def test_mix_max_drift_env_override_and_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("REVERB_MIX_MAX_DRIFT_SECONDS", "4.25")
    config = BackendConfig()
    assert config.mix_max_drift_seconds == 4.25
    assert config.with_projects_dir(tmp_path).mix_max_drift_seconds == 4.25

    with pytest.raises(ValueError, match="REVERB_MIX_MAX_DRIFT_SECONDS"):
        BackendConfig(mix_max_drift_seconds=0)


def _context(
    tmp_path: Path,
    *,
    mix_max_drift_seconds: float = 2.5,
    duration: float = 0.0,
) -> tuple[BackendConfig, PipelineContext]:
    config = BackendConfig(
        mix_max_drift_seconds=mix_max_drift_seconds,
    ).with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record = store.create(str(tmp_path / "input.mp4"), default_job_settings(config))
    record.duration = duration
    return config, PipelineContext(config=config, job=record, project_dir=record.project_dir)


def _prepare_mix(
    context: PipelineContext,
    segments: list[TranslationSegment],
    *,
    wav_duration: float,
    cues: list[SubtitleCue] | None = None,
) -> FakeMixer:
    write_translation(context.project_dir, _translation(*segments))
    if cues is None:
        cues = [
            SubtitleCue(
                id=index,
                start=segment.start,
                end=segment.end,
                lines=[segment.target],
                segmentIds=[segment.id],
            )
            for index, segment in enumerate(segments)
        ]
    write_subtitles(context.project_dir, Subtitles(cues=cues))
    (context.project_dir / AUDIO_PATH).write_bytes(_wav_bytes(context.job.duration))
    for segment in segments:
        path = _segment_wav_path(context.project_dir, segment.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_wav_bytes(wav_duration))
    return FakeMixer()


def _translation(*segments: TranslationSegment) -> Translation:
    return Translation(
        model="local-model",
        sourceLanguage="en",
        targetLanguage="ja",
        segments=list(segments),
    )


def _segment(segment_id: int, start: float, end: float, target: str) -> TranslationSegment:
    return TranslationSegment(
        id=segment_id,
        start=start,
        end=end,
        source="source",
        target=target,
    )


def _wav_bytes(duration: float, sample_rate: int = 24_000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00" * int(duration * sample_rate) * 2)
    return buffer.getvalue()


def _segment_wav_path(project_dir: Path, segment_id: int) -> Path:
    return artifacts.get_segment_wav_path(project_dir, segment_id)
