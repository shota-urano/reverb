from __future__ import annotations

from pydantic import BaseModel, Field


class DependencyStatus(BaseModel):
    ffmpeg: bool
    mlx_whisper: bool = Field(alias="mlx_whisper")
    ollama: bool
    voicevox: bool


class HealthResponse(BaseModel):
    status: str
    version: str
    dependencies: DependencyStatus
