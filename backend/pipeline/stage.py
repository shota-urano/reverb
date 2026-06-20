from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.config import BackendConfig
from core.job_store import JobRecord
from schemas.enums import StageName


def _noop_progress(_: float) -> None:
    return None


@dataclass
class PipelineContext:
    config: BackendConfig
    job: JobRecord
    project_dir: Path
    report_progress: Callable[[float], None] = _noop_progress


class Stage(ABC):
    name: StageName

    @abstractmethod
    def run(self, context: PipelineContext) -> str:
        """Run the stage and return the relative artifact path."""
