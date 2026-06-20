from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from core.config import BackendConfig


class STTSettings(BaseModel):
    model: str
    language: Optional[str] = None


class TranslateSettings(BaseModel):
    model: str


class TTSSettings(BaseModel):
    speakerId: int
    styleId: int


class MixSettings(BaseModel):
    jaVolume: float
    originalVolume: float


class JobSettings(BaseModel):
    stt: STTSettings
    translate: TranslateSettings
    tts: TTSSettings
    mix: MixSettings


def default_job_settings(config: BackendConfig) -> JobSettings:
    return JobSettings(
        stt=STTSettings(model=config.default_stt_model, language=None),
        translate=TranslateSettings(model=config.default_translate_model),
        tts=TTSSettings(speakerId=config.default_speaker_id, styleId=config.default_style_id),
        mix=MixSettings(jaVolume=config.ja_volume, originalVolume=config.original_volume),
    )
