from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Callable, Optional, Protocol

from core.artifacts import AUDIO_PATH, VOICEOVER_PATH, get_cue_wav_path, read_subtitles
from core.errors import StageError
from core.progress_reporter import _EstimatedProgressReporter
from pipeline.stage import PipelineContext, Stage
from pipeline.tts import TtsSynthesizer
from schemas.artifacts import SubtitleCue
from schemas.enums import StageName

logger = logging.getLogger(__name__)

_MIN_SPEED_SCALE = 1.0
_MAX_SPEED_SCALE = 1.3
_SPEED_SCALE_EPSILON = 0.000001
_FATAL_STAGE_ERROR_CODES = {"TTS_UNAVAILABLE", "SPEAKER_INVALID"}


class AudioMixer(Protocol):
    def mix_voiceover(
        self,
        original_audio_path: Path,
        cue_inputs: list[tuple[Path, float]],
        out_path: Path,
        duration: float,
        ja_volume: float,
        original_volume: float,
    ) -> None: ...


class MixStage(Stage):
    name = StageName.mix

    def __init__(self, mixer: AudioMixer, synthesizer: TtsSynthesizer) -> None:
        self.mixer = mixer
        self.synthesizer = synthesizer

    def run(self, context: PipelineContext) -> str:
        context.report_progress(0.0)
        subtitles = read_subtitles(context.project_dir)
        total_cues = len(subtitles.cues)
        total_progress_items = total_cues + 1
        cue_inputs: list[tuple[Path, float]] = []

        if total_cues == 0:
            self._run_progress_item(
                context,
                index=0,
                total_items=total_progress_items,
                work=lambda: self._mix(context, cue_inputs, context.job.duration),
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
        next_available_start = 0.0
        compressed = 0
        equal_speed = 0
        skipped = 0

        for index, cue in enumerate(subtitles.cues):
            result: tuple[Optional[float], Optional[float], bool] = (None, None, False)

            def prepare() -> None:
                nonlocal result
                path = get_cue_wav_path(context.project_dir, cue.id)
                result = self._prepare_cue(context, cue, path, speaker_id, style_id)

            self._run_progress_item(
                context,
                index=index,
                total_items=total_progress_items,
                work=prepare,
            )
            path = get_cue_wav_path(context.project_dir, cue.id)
            duration, speed_scale, skipped_target = result
            if skipped_target:
                skipped += 1
            elif speed_scale is not None:
                if speed_scale > 1.0:
                    compressed += 1
                elif abs(speed_scale - 1.0) <= _SPEED_SCALE_EPSILON:
                    equal_speed += 1
            if duration is not None:
                placement_start = max(cue.start, next_available_start)
                cue_inputs.append((path, placement_start))
                next_available_start = placement_start + duration

        logger.info(
            "speed_scale distribution: total=%d compressed(>1.0)=%d "
            "equal_speed(=1.0)=%d skipped(target<=0)=%d",
            total_cues,
            compressed,
            equal_speed,
            skipped,
        )
        self._run_progress_item(
            context,
            index=total_cues,
            total_items=total_progress_items,
            work=lambda: self._mix(
                context,
                cue_inputs,
                _output_duration(context, subtitles.cues, cue_inputs),
            ),
        )
        return str(VOICEOVER_PATH)

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

    def _prepare_cue(
        self,
        context: PipelineContext,
        cue: SubtitleCue,
        path: Path,
        speaker_id: int,
        style_id: int,
    ) -> tuple[Optional[float], Optional[float], bool]:
        duration = _wav_duration_seconds(path)
        if duration is None:
            _warn_missing_cue(cue.id, path)
            return None, None, False

        target = cue.end - cue.start
        if target <= 0:
            logger.warning(
                "Skipping TTS cue with non-positive target duration.",
                extra={"cue_id": cue.id, "start": cue.start, "end": cue.end},
            )
            return None, None, True

        speed_scale = _clamp(duration / target, _MIN_SPEED_SCALE, _MAX_SPEED_SCALE)
        logger.info(
            "cue speed_scale",
            extra={"cue_id": cue.id, "speed_scale": speed_scale},
        )
        if abs(speed_scale - 1.0) <= _SPEED_SCALE_EPSILON:
            return duration, speed_scale, False

        text = _cue_text(cue.lines)
        if not text:
            return duration, speed_scale, False

        resynthesized = self._resynthesize_cue(
            context, text, speaker_id, style_id, speed_scale, cue.id
        )
        if resynthesized is None:
            return None, speed_scale, False

        path.write_bytes(resynthesized)
        resynthesized_duration = _wav_duration_seconds(path)
        if resynthesized_duration is None:
            _warn_missing_cue(cue.id, path)
            return None, speed_scale, False
        return resynthesized_duration, speed_scale, False

    def _resynthesize_cue(
        self,
        context: PipelineContext,
        text: str,
        speaker_id: int,
        style_id: int,
        speed_scale: float,
        cue_id: int,
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
            "TTS cue resynthesis failed after retries; continuing without this cue.",
            extra={"cue_id": cue_id, "error": str(last_error)},
        )
        return None

    def _mix(
        self,
        context: PipelineContext,
        cue_inputs: list[tuple[Path, float]],
        duration: float,
    ) -> None:
        self.mixer.mix_voiceover(
            context.project_dir / AUDIO_PATH,
            cue_inputs,
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


def _warn_missing_cue(cue_id: int, path: Path) -> None:
    logger.warning(
        "Skipping missing or empty TTS cue; original audio remains for this interval.",
        extra={"cue_id": cue_id, "path": str(path)},
    )


def _output_duration(
    context: PipelineContext,
    cues: list[SubtitleCue],
    cue_inputs: list[tuple[Path, float]],
) -> float:
    if context.job.duration > 0:
        return context.job.duration
    cue_end = max((cue.end for cue in cues), default=0.0)
    placed_end = 0.0
    for path, start in cue_inputs:
        cue_duration = _wav_duration_seconds(path)
        if cue_duration is not None:
            placed_end = max(placed_end, start + cue_duration)
    return max(cue_end, placed_end)
