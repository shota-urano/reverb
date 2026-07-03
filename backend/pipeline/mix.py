from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol

from core.artifacts import (
    AUDIO_PATH,
    VOICEOVER_PATH,
    get_segment_wav_path,
    read_subtitles,
    read_translation,
    write_subtitles,
)
from core.errors import StageError
from core.progress_reporter import _EstimatedProgressReporter
from pipeline.stage import PipelineContext, Stage
from pipeline.tts import TtsSynthesizer
from schemas.artifacts import Subtitles, TranslationSegment
from schemas.enums import StageName

logger = logging.getLogger(__name__)

_MIN_SPEED_SCALE = 1.0
_MAX_SPEED_SCALE = 1.3
_SPEED_SCALE_EPSILON = 0.000001
_ZERO_DURATION_EPSILON = 0.000001
_FATAL_STAGE_ERROR_CODES = {"TTS_UNAVAILABLE", "SPEAKER_INVALID"}


class AudioMixer(Protocol):
    def mix_voiceover(
        self,
        original_audio_path: Path,
        clip_inputs: list[tuple[Path, float, Optional[float]]],
        out_path: Path,
        duration: float,
        ja_volume: float,
        original_volume: float,
    ) -> None: ...


@dataclass
class _PlacedAudio:
    segment_id: int
    path: Path
    start: float
    duration: float
    length_limit: Optional[float] = None


class MixStage(Stage):
    name = StageName.mix

    def __init__(self, mixer: AudioMixer, synthesizer: TtsSynthesizer) -> None:
        self.mixer = mixer
        self.synthesizer = synthesizer

    def run(self, context: PipelineContext) -> str:
        context.report_progress(0.0)
        subtitles = read_subtitles(context.project_dir)
        translation = read_translation(context.project_dir)
        segments = sorted(translation.segments, key=lambda segment: (segment.start, segment.id))
        total_segments = len(segments)
        total_progress_items = total_segments + 1
        placed_audio: list[_PlacedAudio] = []

        if total_segments == 0:
            self._write_audio_aligned_subtitles(context, subtitles, {})
            self._run_progress_item(
                context,
                index=0,
                total_items=total_progress_items,
                work=lambda: self._mix(context, [], context.job.duration),
            )
            return str(VOICEOVER_PATH)

        speaker_id = _setting_value(
            context.job.settings.tts,
            "speakerId",
            context.config.default_speaker_id,
        )
        style_id = _setting_value(
            context.job.settings.tts,
            "styleId",
            context.config.default_style_id,
        )
        compressed = 0
        equal_speed = 0
        skipped = 0
        drift_cap_fired = 0

        for index, segment in enumerate(segments):
            result: tuple[Optional[float], Optional[float], bool] = (None, None, False)

            def prepare() -> None:
                nonlocal result
                path = get_segment_wav_path(context.project_dir, segment.id)
                result = self._prepare_segment(context, segment, path, speaker_id, style_id)

            self._run_progress_item(
                context,
                index=index,
                total_items=total_progress_items,
                work=prepare,
            )
            path = get_segment_wav_path(context.project_dir, segment.id)
            duration, speed_scale, skipped_target = result
            if skipped_target:
                skipped += 1
            elif speed_scale is not None:
                if speed_scale > 1.0:
                    compressed += 1
                elif abs(speed_scale - 1.0) <= _SPEED_SCALE_EPSILON:
                    equal_speed += 1
            if duration is not None and duration > _ZERO_DURATION_EPSILON:
                previous_end = (
                    placed_audio[-1].start + placed_audio[-1].duration
                    if placed_audio
                    else segment.start
                )
                uncapped_start = max(segment.start, previous_end)
                capped_start = segment.start + context.config.mix_max_drift_seconds
                placement_start = min(uncapped_start, capped_start)
                if uncapped_start > capped_start:
                    drift_cap_fired += 1
                if placed_audio and placement_start < previous_end:
                    previous = placed_audio[-1]
                    trimmed_duration = max(0.0, placement_start - previous.start)
                    previous.duration = trimmed_duration
                    previous.length_limit = trimmed_duration
                    # 全カットされたクリップはゼロ長ストリームとして ffmpeg に
                    # 渡さない（job.duration=0 経路では apad が無く amix が壊れる）。
                    if trimmed_duration <= _ZERO_DURATION_EPSILON:
                        placed_audio.pop()
                placed_audio.append(
                    _PlacedAudio(
                        segment_id=segment.id,
                        path=path,
                        start=placement_start,
                        duration=duration,
                    )
                )

        # 旧成果物スキーム（tts/cue_*.wav）のプロジェクトを途中再開した場合など、
        # 発話すべきセグメントがあるのに1つも配置できないときは、日本語音声ゼロの
        # voiceover を黙って完成させず明示的に失敗させる。
        if not placed_audio and _has_speakable_segment(segments):
            raise StageError(
                "MIX_INPUTS_MISSING",
                "No TTS segment audio (tts/seg_*.wav) was found for any translation "
                "segment. Legacy per-cue TTS artifacts are incompatible; reprocess "
                "the video to regenerate TTS output.",
            )

        placement_by_segment = {
            placed.segment_id: (placed.start, placed.duration) for placed in placed_audio
        }
        self._write_audio_aligned_subtitles(context, subtitles, placement_by_segment)

        logger.info(
            "speed_scale distribution: total=%d compressed(>1.0)=%d "
            "equal_speed(=1.0)=%d skipped(target<=0)=%d",
            total_segments,
            compressed,
            equal_speed,
            skipped,
        )
        logger.info(
            "mix drift cap summary: total=%d fired=%d max_drift_seconds=%.3f",
            total_segments,
            drift_cap_fired,
            context.config.mix_max_drift_seconds,
        )
        clip_inputs = [(placed.path, placed.start, placed.length_limit) for placed in placed_audio]
        self._run_progress_item(
            context,
            index=total_segments,
            total_items=total_progress_items,
            work=lambda: self._mix(
                context,
                clip_inputs,
                _output_duration(context, segments, clip_inputs),
            ),
        )
        return str(VOICEOVER_PATH)

    def _write_audio_aligned_subtitles(
        self,
        context: PipelineContext,
        subtitles: "Subtitles",
        placement_by_segment: dict[int, tuple[float, float]],
    ) -> None:
        """各 cue に音声の実配置時刻 audioStart/audioEnd を付与して書き戻す。

        segment の配置区間を、その segment に属する cue の文字数比で連続分割する。
        音声未配置の cue は None とし、最低表示時間は次の配置 cue の開始を上限にする。
        """
        for cue in subtitles.cues:
            cue.audioStart = None
            cue.audioEnd = None

        portions_by_index: dict[int, list[tuple[float, float]]] = {}
        for segment_id, (audio_start, audio_duration) in sorted(
            placement_by_segment.items(), key=lambda item: item[1][0]
        ):
            cue_indices = [
                index for index, cue in enumerate(subtitles.cues) if segment_id in cue.segmentIds
            ]
            if not cue_indices:
                continue
            weights = [len(_cue_text(subtitles.cues[index].lines)) for index in cue_indices]
            total_weight = sum(weights)
            if total_weight <= 0:
                weights = [1] * len(cue_indices)
                total_weight = len(cue_indices)
            cursor = audio_start
            placed_end = audio_start + audio_duration
            for position, (cue_index, weight) in enumerate(zip(cue_indices, weights)):
                portion_end = (
                    placed_end
                    if position == len(cue_indices) - 1
                    else cursor + audio_duration * weight / total_weight
                )
                portions_by_index.setdefault(cue_index, []).append((cursor, portion_end))
                cursor = portion_end

        min_duration = context.config.subtitle_min_duration_seconds
        placed_indices = sorted(portions_by_index)
        raw_intervals = {
            index: (
                min(start for start, _ in portions_by_index[index]),
                max(end for _, end in portions_by_index[index]),
            )
            for index in placed_indices
        }
        next_start = {
            current: raw_intervals[nxt][0]
            for current, nxt in zip(placed_indices, placed_indices[1:])
        }
        for index in placed_indices:
            audio_start, raw_end = raw_intervals[index]
            desired_end = max(raw_end, audio_start + min_duration)
            ceiling = next_start.get(index)
            audio_end = min(desired_end, ceiling) if ceiling is not None else desired_end
            cue = subtitles.cues[index]
            cue.audioStart = audio_start
            cue.audioEnd = max(audio_start, audio_end)
        write_subtitles(context.project_dir, subtitles)

    def _run_progress_item(
        self,
        context: PipelineContext,
        *,
        index: int,
        total_items: int,
        work: Callable[[], None],
    ) -> None:
        base_progress = index / total_items
        ceiling_progress = (index + 1) / total_items
        reporter = _EstimatedProgressReporter(
            progress_cb=context.report_progress,
            estimated_total_seconds=context.config.mix_progress_estimated_item_seconds,
            base_progress=base_progress,
            ceiling_progress=ceiling_progress,
            interval_seconds=context.config.mix_progress_interval_seconds,
            thread_name="mix-progress",
        )
        reporter.start()
        try:
            work()
        finally:
            reporter.stop()
        context.report_progress(ceiling_progress)

    def _prepare_segment(
        self,
        context: PipelineContext,
        segment: TranslationSegment,
        path: Path,
        speaker_id: int,
        style_id: int,
    ) -> tuple[Optional[float], Optional[float], bool]:
        duration = _wav_duration_seconds(path)
        if duration is None:
            _warn_missing_segment(segment.id, path)
            return None, None, False

        target = segment.end - segment.start
        if target <= 0:
            logger.warning(
                "Skipping TTS segment with non-positive target duration.",
                extra={"segment_id": segment.id, "start": segment.start, "end": segment.end},
            )
            return None, None, True

        speed_scale = _clamp(duration / target, _MIN_SPEED_SCALE, _MAX_SPEED_SCALE)
        logger.info(
            "segment speed_scale",
            extra={"segment_id": segment.id, "speed_scale": speed_scale},
        )
        if abs(speed_scale - 1.0) <= _SPEED_SCALE_EPSILON:
            return duration, speed_scale, False

        text = segment.target.strip()
        if not text:
            return duration, speed_scale, False

        resynthesized = self._resynthesize_segment(
            context, text, speaker_id, style_id, speed_scale, segment.id
        )
        if resynthesized is None:
            return None, speed_scale, False

        path.write_bytes(resynthesized)
        resynthesized_duration = _wav_duration_seconds(path)
        if resynthesized_duration is None:
            _warn_missing_segment(segment.id, path)
            return None, speed_scale, False
        return resynthesized_duration, speed_scale, False

    def _resynthesize_segment(
        self,
        context: PipelineContext,
        text: str,
        speaker_id: int,
        style_id: int,
        speed_scale: float,
        segment_id: int,
    ) -> Optional[bytes]:
        attempts = context.config.tts_cue_retry_count + 1
        last_error: Optional[StageError] = None

        for _ in range(attempts):
            try:
                return self.synthesizer.synthesize(text, speaker_id, style_id, speed_scale)
            except StageError as exc:
                if exc.code in _FATAL_STAGE_ERROR_CODES:
                    raise
                last_error = exc

        logger.warning(
            "TTS segment resynthesis failed after retries; continuing without this segment.",
            extra={"segment_id": segment_id, "error": str(last_error)},
        )
        return None

    def _mix(
        self,
        context: PipelineContext,
        clip_inputs: list[tuple[Path, float, Optional[float]]],
        duration: float,
    ) -> None:
        self.mixer.mix_voiceover(
            context.project_dir / AUDIO_PATH,
            clip_inputs,
            context.project_dir / VOICEOVER_PATH,
            duration,
            context.config.ja_volume,
            context.config.original_volume,
        )


def _setting_value(settings, field_name: str, default: int) -> int:
    value = getattr(settings, field_name, None)
    return default if value is None else value


def _cue_text(lines: list[str]) -> str:
    return "".join(line.strip() for line in lines).strip()


def _has_speakable_segment(segments: list[TranslationSegment]) -> bool:
    return any(segment.target.strip() and segment.end - segment.start > 0 for segment in segments)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _wav_duration_seconds(path: Path) -> Optional[float]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with wave.open(str(path), "rb") as wav:
            frame_rate = wav.getframerate()
            if frame_rate <= 0:
                return None
            return wav.getnframes() / frame_rate
    except (EOFError, OSError, wave.Error):
        return None


def _warn_missing_segment(segment_id: int, path: Path) -> None:
    logger.warning(
        "Skipping missing or empty TTS segment; original audio remains for this interval.",
        extra={"segment_id": segment_id, "path": str(path)},
    )


def _output_duration(
    context: PipelineContext,
    segments: list[TranslationSegment],
    clip_inputs: list[tuple[Path, float, Optional[float]]],
) -> float:
    if context.job.duration > 0:
        return context.job.duration
    segment_end = max((segment.end for segment in segments), default=0.0)
    placed_end = 0.0
    for path, start, length_limit in clip_inputs:
        clip_duration = _wav_duration_seconds(path)
        if clip_duration is not None:
            if length_limit is not None:
                clip_duration = min(clip_duration, length_limit)
            placed_end = max(placed_end, start + clip_duration)
    return max(segment_end, placed_end)
