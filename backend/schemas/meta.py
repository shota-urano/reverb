from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class ModelsResponse(BaseModel):
    default_model: str = Field(alias="default")
    models: List[str]


class Speaker(BaseModel):
    speakerId: int
    name: str
    styleId: int


class SpeakersResponse(BaseModel):
    default_speaker: Speaker = Field(alias="default")
    speakers: List[Speaker]
