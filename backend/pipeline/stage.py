from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from core.config import BackendConfig
from core.job_store import JobRecord
from schemas.enums import StageName


@dataclass
class PipelineContext:
    config: BackendConfig
    job: JobRecord
    project_dir: Path


class Stage(ABC):
    name: StageName

    @abstractmethod
    def run(self, context: PipelineContext) -> str:
        """Run the stage and return the relative artifact path."""
