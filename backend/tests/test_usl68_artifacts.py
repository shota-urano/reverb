from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.artifacts import (
    ArtifactVersionError,
    get_segment_wav_path,
    read_subtitles,
    read_transcript,
    read_translation,
    write_subtitles,
    write_transcript,
    write_translation,
)
from schemas.artifacts import (
    SubtitleCue,
    Subtitles,
    Transcript,
    TranscriptSegment,
    Translation,
    TranslationSegment,
)


def test_artifact_schemas_round_trip_with_canonical_paths(tmp_path: Path) -> None:
    transcript = Transcript(
        engine="mlx-whisper",
        model="large-v3",
        language="en",
        duration=4.2,
        segments=[TranscriptSegment(id=0, start=0.0, end=4.2, text="Welcome.")],
    )
    translation = Translation(
        model="qwen3:30b",
        sourceLanguage="en",
        targetLanguage="ja",
        segments=[
            TranslationSegment(
                id=0,
                start=0.0,
                end=4.2,
                source="Welcome.",
                target="ようこそ。",
            )
        ],
    )
    subtitles = Subtitles(
        cues=[
            SubtitleCue(
                id=0,
                start=0.0,
                end=4.2,
                lines=["ようこそ。"],
                segmentIds=[0],
            )
        ]
    )

    write_transcript(tmp_path, transcript)
    write_translation(tmp_path, translation)
    write_subtitles(tmp_path, subtitles)

    assert read_transcript(tmp_path) == transcript
    assert read_translation(tmp_path) == translation
    assert read_subtitles(tmp_path) == subtitles
    assert get_segment_wav_path(tmp_path, 7) == tmp_path / "tts" / "seg_0007.wav"


def test_artifact_read_rejects_wrong_version(tmp_path: Path) -> None:
    (tmp_path / "transcript.json").write_text(
        json.dumps(
            {
                "version": 2,
                "engine": "mlx-whisper",
                "model": "large-v3",
                "language": None,
                "duration": 0.0,
                "segments": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactVersionError, match="transcript.json version 2 is not supported"):
        read_transcript(tmp_path)
