from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

import pytest

from core.artifacts import AUDIO_PATH, read_transcript
from core.config import BackendConfig
from core.job_store import JobStore
from pipeline.stage import PipelineContext
from pipeline.transcribe import TranscribeStage, resolve_transcript_language
from schemas.settings import default_job_settings


class FakeWhisperAdapter:
    def __init__(
        self,
        *,
        language_detected: Optional[str],
        segments: list[dict],
    ) -> None:
        self.language_detected = language_detected
        self.segments = segments
        self.calls: list[dict[str, object]] = []

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
        progress_cb(1.0)
        return self.language_detected, self.segments


def test_explicit_language_setting_overrides_whisper_detection(tmp_path: Path) -> None:
    whisper = FakeWhisperAdapter(
        language_detected="ja",
        segments=[{"start": 0.0, "end": 1.0, "text": "Hello world."}],
    )

    transcript = _run_transcribe_stage(tmp_path, whisper, explicit_language="en")

    assert whisper.calls[0]["language"] == "en"
    assert transcript.language == "en"


def test_auto_detected_ja_with_all_english_segments_is_corrected_to_en() -> None:
    language = resolve_transcript_language(
        "ja",
        [
            {"text": "Hello, welcome to the lecture."},
            {"text": "Today we discuss local inference."},
        ],
    )

    assert language == "en"


def test_auto_detected_ja_with_japanese_characters_is_not_corrected() -> None:
    language = resolve_transcript_language(
        "ja",
        [{"text": "Hello こんにちは"}],
    )

    assert language == "ja"


def test_auto_detected_ja_without_cjk_or_latin_dominance_returns_unknown_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="pipeline.transcribe")

    language = resolve_transcript_language("ja", [{"text": "12345 !!!"}])

    assert language is None
    assert "no CJK characters" in caplog.text


@pytest.mark.parametrize("text", ["こんにちは", "Plain English text"])
def test_detected_en_is_unchanged_regardless_of_text_content(text: str) -> None:
    language = resolve_transcript_language("en", [{"text": text}])

    assert language == "en"


def _run_transcribe_stage(
    tmp_path: Path,
    whisper: FakeWhisperAdapter,
    *,
    explicit_language: Optional[str],
):
    config = BackendConfig().with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record = store.create("/tmp/input.mp4", default_job_settings(config))
    record.settings.stt.language = explicit_language
    (record.project_dir / AUDIO_PATH).write_bytes(b"wav")

    TranscribeStage(whisper).run(
        PipelineContext(
            config=config,
            job=record,
            project_dir=record.project_dir,
            report_progress=lambda _: None,
        )
    )

    return read_transcript(record.project_dir)
