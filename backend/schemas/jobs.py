from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from core.errors import ErrorBody
from schemas.enums import JobState, StageName, StageState
from schemas.settings import JobSettings


class CreateJobRequest(BaseModel):
    videoPath: str
    settings: Optional[JobSettings] = None


class CreateJobResponse(BaseModel):
    jobId: str
    projectId: str
    status: JobState


class StageProgress(BaseModel):
    name: StageName
    status: StageState
    progress: float


class JobStatus(BaseModel):
    jobId: str
    projectId: str
    status: JobState
    currentStage: Optional[StageName]
    progress: float
    stages: List[StageProgress]
    error: Optional[ErrorBody]


class JobResult(BaseModel):
    projectId: str
    videoPath: str
    voiceoverPath: str
    subtitlesPath: str
    duration: float
