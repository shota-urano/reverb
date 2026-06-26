from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    start: float
    end: float
    text: str


class Transcript(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: int = 1
    engine: str
    model: str
    language: Optional[str]
    duration: float
    segments: List[TranscriptSegment]


class TranslationSegment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    start: float
    end: float
    source: str
    target: str


class Translation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: int = 1
    model: str
    sourceLanguage: Optional[str]
    targetLanguage: str
    segments: List[TranslationSegment]


class SubtitleCue(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    start: float
    end: float
    lines: List[str]
    segmentIds: List[int]
    # 吹き替え音声の実配置時刻（mix が尺合わせ後の placement を書き込む・任意）。
    # start/end（元動画時間軸）は不変。プレーヤーは在ればこの窓で表示同期する。
    audioStart: Optional[float] = None
    audioEnd: Optional[float] = None


class Subtitles(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: int = 1
    cues: List[SubtitleCue]
