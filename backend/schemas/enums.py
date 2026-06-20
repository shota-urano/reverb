from __future__ import annotations

from enum import Enum


class StageName(str, Enum):
    extract = "extract"
    transcribe = "transcribe"
    translate = "translate"
    subtitle = "subtitle"
    tts = "tts"
    mix = "mix"


STAGE_ORDER = [
    StageName.extract,
    StageName.transcribe,
    StageName.translate,
    StageName.subtitle,
    StageName.tts,
    StageName.mix,
]


class JobState(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    canceled = "canceled"


class StageState(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    canceled = "canceled"
