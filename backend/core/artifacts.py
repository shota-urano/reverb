from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Type, TypeVar

from core.serialization import model_to_dict
from schemas.artifacts import Subtitles, Transcript, Translation

SCHEMA_VERSION = 1

AUDIO_PATH = Path("audio.wav")
TRANSCRIPT_PATH = Path("transcript.json")
TRANSLATION_PATH = Path("translation.json")
SUBTITLES_PATH = Path("subtitles.json")
TTS_DIR = Path("tts")
VOICEOVER_PATH = Path("voiceover.wav")

T = TypeVar("T")


class ArtifactVersionError(ValueError):
    pass


def get_cue_wav_path(project_dir: Path, cue_id: int) -> Path:
    return project_dir / TTS_DIR / f"cue_{cue_id:04d}.wav"


def write_transcript(project_dir: Path, transcript: Transcript) -> Path:
    return _write_model(project_dir / TRANSCRIPT_PATH, transcript)


def read_transcript(project_dir: Path) -> Transcript:
    return _read_model(project_dir / TRANSCRIPT_PATH, Transcript)


def write_translation(project_dir: Path, translation: Translation) -> Path:
    return _write_model(project_dir / TRANSLATION_PATH, translation)


def read_translation(project_dir: Path) -> Translation:
    return _read_model(project_dir / TRANSLATION_PATH, Translation)


def write_subtitles(project_dir: Path, subtitles: Subtitles) -> Path:
    return _write_model(project_dir / SUBTITLES_PATH, subtitles)


def read_subtitles(project_dir: Path) -> Subtitles:
    return _read_model(project_dir / SUBTITLES_PATH, Subtitles)


def _write_model(path: Path, model) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(model_to_dict(model, by_alias=True), ensure_ascii=False, indent=2)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)
    return path


def _read_model(path: Path, model_class: Type[T]) -> T:
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = payload.get("version")
    if version != SCHEMA_VERSION:
        raise ArtifactVersionError(
            f"{path.name} version {version} is not supported; expected {SCHEMA_VERSION}"
        )
    return model_class(**payload)
