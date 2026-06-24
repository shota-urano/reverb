from __future__ import annotations

import io
import time
import wave
from pathlib import Path
from typing import Callable, Optional

from core.artifacts import AUDIO_PATH, get_cue_wav_path, write_subtitles, write_transcript
from core.config import BackendConfig
from core.job_store import JobRecord, JobStore
from pipeline.mix import MixStage
from pipeline.stage import PipelineContext
from pipeline.translate import TranslateStage
from pipeline.tts import TtsStage
from schemas.artifacts import SubtitleCue, Subtitles, Transcript, TranscriptSegment
from schemas.settings import default_job_settings


class SlowTranslator:
    def __init__(self, progress_values: list[float]) -> None:
        self.progress_values = progress_values

    def warm_up(self, model: str, system_prompt: str) -> None:
        return None

    def translate(
        self,
        segments: list[dict[str, object]],
        model: str,
        source_lang: Optional[str],
        system_prompt: str,
        context_window: int,
    ) -> list[str]:
        _wait_for_intermediate_values(self.progress_values, minimum=2)
        return [f"訳{segment['id']}" for segment in segments if not segment.get("contextOnly")]


class SlowSynthesizer:
    def __init__(self, progress_values: list[float]) -> None:
        self.progress_values = progress_values

    def ping(self) -> bool:
        return True

    def list_speakers(self) -> list:
        return []

    def synthesize(
        self,
        text: str,
        speaker_id: int,
        style_id: int,
        speed_scale: float = 1.0,
    ) -> bytes:
        _wait_for_intermediate_values(self.progress_values, minimum=1)
        return _wav_bytes(1.0)


class SlowMixer:
    def __init__(self, progress_values: list[float]) -> None:
        self.progress_values = progress_values

    def mix_voiceover(
        self,
        original_audio_path: Path,
        cue_inputs: list[tuple[Path, float]],
        out_path: Path,
        duration: float,
        ja_volume: float,
        original_volume: float,
    ) -> None:
        _wait_for_intermediate_values(self.progress_values, minimum=1)
        out_path.write_bytes(b"voiceover")


def test_translate_reports_intermediate_monotonic_progress_per_chunk(tmp_path: Path) -> None:
    progress_values: list[float] = []
    context = _context(
        tmp_path,
        progress_values.append,
        BackendConfig(
            translate_chunk_size=1,
            translate_progress_estimated_chunk_seconds=0.05,
            translate_progress_interval_seconds=0.005,
        ),
    )
    write_transcript(
        context.project_dir,
        Transcript(
            engine=context.config.default_stt_engine,
            model=context.job.settings.stt.model,
            language="en",
            duration=2.0,
            segments=[
                TranscriptSegment(id=0, start=0.0, end=1.0, text="Hello."),
                TranscriptSegment(id=1, start=1.0, end=2.0, text="World."),
            ],
        ),
    )

    TranslateStage(SlowTranslator(progress_values)).run(context)

    assert _intermediate_values(progress_values) >= 2
    assert _strictly_increasing(progress_values)
    assert progress_values[-1] == 1.0
    assert all(0.0 <= value <= 1.0 for value in progress_values)


def test_tts_reports_intermediate_monotonic_progress_per_cue(tmp_path: Path) -> None:
    progress_values: list[float] = []
    context = _context(
        tmp_path,
        progress_values.append,
        BackendConfig(
            tts_progress_estimated_cue_seconds=0.05,
            tts_progress_interval_seconds=0.005,
        ),
    )
    write_subtitles(
        context.project_dir,
        Subtitles(
            cues=[
                SubtitleCue(id=0, start=0.0, end=1.0, lines=["こんにちは。"], segmentIds=[0]),
            ]
        ),
    )

    TtsStage(SlowSynthesizer(progress_values)).run(context)

    assert _intermediate_values(progress_values) >= 1
    assert _strictly_increasing(progress_values)
    assert progress_values[-1] == 1.0
    assert all(0.0 <= value <= 1.0 for value in progress_values)


def test_mix_reports_intermediate_monotonic_progress_while_mixing(tmp_path: Path) -> None:
    progress_values: list[float] = []
    context = _context(
        tmp_path,
        progress_values.append,
        BackendConfig(
            mix_progress_estimated_item_seconds=0.05,
            mix_progress_interval_seconds=0.005,
        ),
    )
    context.job.duration = 2.0
    (context.project_dir / AUDIO_PATH).write_bytes(_wav_bytes(2.0))
    write_subtitles(
        context.project_dir,
        Subtitles(
            cues=[
                SubtitleCue(id=0, start=0.0, end=1.0, lines=["長い音声。"], segmentIds=[0]),
            ]
        ),
    )
    cue_path = get_cue_wav_path(context.project_dir, 0)
    cue_path.parent.mkdir(parents=True, exist_ok=True)
    cue_path.write_bytes(_wav_bytes(1.0))

    MixStage(SlowMixer(progress_values), SlowSynthesizer(progress_values)).run(context)

    assert _intermediate_values(progress_values) >= 1
    assert _strictly_increasing(progress_values)
    assert progress_values[-1] == 1.0
    assert all(0.0 <= value <= 1.0 for value in progress_values)


def _context(
    tmp_path: Path,
    report_progress: Callable[[float], None],
    config: BackendConfig,
) -> PipelineContext:
    config = config.with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record: JobRecord = store.create(str(tmp_path / "input.mp4"), default_job_settings(config))
    return PipelineContext(
        config=config,
        job=record,
        project_dir=record.project_dir,
        report_progress=report_progress,
    )


def _wait_for_intermediate_values(
    values: list[float],
    *,
    minimum: int,
    timeout_seconds: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while _intermediate_values(values) < minimum and time.monotonic() < deadline:
        time.sleep(0.001)


def _intermediate_values(values: list[float]) -> int:
    return sum(1 for value in values if 0.0 < value < 1.0)


def _strictly_increasing(values: list[float]) -> bool:
    return all(current > previous for previous, current in zip(values, values[1:]))


def _wav_bytes(duration: float, sample_rate: int = 24_000) -> bytes:
    buffer = io.BytesIO()
    frame_count = int(duration * sample_rate)
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00" * frame_count * 2)
    return buffer.getvalue()
