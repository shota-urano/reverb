from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Optional, Protocol

from core.artifacts import TTS_DIR, get_cue_wav_path, read_subtitles
from core.errors import StageError
from pipeline.stage import PipelineContext, Stage
from schemas.enums import StageName

logger = logging.getLogger(__name__)

_SILENT_SAMPLE_RATE = 24000
_SILENT_CHANNELS = 1
_SILENT_SAMPLE_WIDTH_BYTES = 2
_SILENT_DURATION_SECONDS = 0.5
_FATAL_STAGE_ERROR_CODES = {"VOICEVOX_UNAVAILABLE", "SPEAKER_INVALID"}


class TtsSynthesizer(Protocol):
    def synthesize(
        self,
        text: str,
        speaker_id: int,
        style_id: int,
        speed_scale: float = 1.0,
    ) -> bytes: ...


class TtsStage(Stage):
    name = StageName.tts

    def __init__(self, adapter: TtsSynthesizer) -> None:
        self.adapter = adapter

    def run(self, context: PipelineContext) -> str:
        context.report_progress(0.0)
        subtitles = read_subtitles(context.project_dir)
        tts_dir = context.project_dir / TTS_DIR
        tts_dir.mkdir(parents=True, exist_ok=True)

        total_cues = len(subtitles.cues)
        if total_cues == 0:
            context.report_progress(1.0)
            return str(TTS_DIR)

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

        for index, cue in enumerate(subtitles.cues):
            path = get_cue_wav_path(context.project_dir, cue.id)
            text = _cue_text(cue.lines)
            if text:
                wav_bytes = self._synthesize_cue(context, text, speaker_id, style_id, cue.id)
                path.write_bytes(wav_bytes)
            else:
                _write_silent_wav(path)
            context.report_progress((index + 1) / total_cues)

        # TTS emits multiple cue files; the stage artifact is the containing directory.
        return str(TTS_DIR)

    def _synthesize_cue(
        self,
        context: PipelineContext,
        text: str,
        speaker_id: int,
        style_id: int,
        cue_id: int,
    ) -> bytes:
        attempts = context.config.tts_cue_retry_count + 1
        last_error: Optional[Exception] = None

        for _ in range(attempts):
            try:
                return self.adapter.synthesize(text, speaker_id, style_id, speed_scale=1.0)
            except StageError as exc:
                if exc.code in _FATAL_STAGE_ERROR_CODES:
                    raise
                last_error = exc
            except Exception as exc:
                last_error = exc

        logger.warning(
            "TTS cue synthesis failed after retries; writing silent placeholder.",
            extra={"cue_id": cue_id, "error": str(last_error)},
        )
        path = get_cue_wav_path(context.project_dir, cue_id)
        _write_silent_wav(path)
        return path.read_bytes()


def _setting_value(settings, field_name: str, default: int) -> int:
    value = getattr(settings, field_name, None)
    return default if value is None else value


def _cue_text(lines: list[str]) -> str:
    return "".join(line.strip() for line in lines).strip()


def _write_silent_wav(path: Path) -> None:
    frame_count = int(_SILENT_SAMPLE_RATE * _SILENT_DURATION_SECONDS)
    silence = b"\x00" * frame_count * _SILENT_CHANNELS * _SILENT_SAMPLE_WIDTH_BYTES
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(_SILENT_CHANNELS)
        wav.setsampwidth(_SILENT_SAMPLE_WIDTH_BYTES)
        wav.setframerate(_SILENT_SAMPLE_RATE)
        wav.writeframes(silence)
