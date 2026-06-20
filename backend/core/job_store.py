from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Callable, Dict, List, Optional

from core.errors import BackendError, ErrorBody
from core.ids import new_job_id, new_project_id
from core.serialization import model_to_dict
from schemas.enums import STAGE_ORDER, JobState, StageName, StageState
from schemas.jobs import JobResult, JobStatus, StageProgress
from schemas.settings import JobSettings


@dataclass
class StageRecord:
    name: StageName
    status: StageState = StageState.pending
    progress: float = 0.0
    artifact: Optional[str] = None


@dataclass
class JobRecord:
    job_id: str
    project_id: str
    video_path: str
    settings: JobSettings
    project_dir: Path
    status: JobState = JobState.queued
    current_stage: Optional[StageName] = None
    stages: Dict[StageName, StageRecord] = field(
        default_factory=lambda: {name: StageRecord(name=name) for name in STAGE_ORDER}
    )
    error: Optional[ErrorBody] = None
    duration: float = 0.0

    def snapshot(self) -> JobStatus:
        stages = [
            StageProgress(
                name=stage.name,
                status=stage.status,
                progress=round(stage.progress, 4),
            )
            for stage in self.stages.values()
        ]
        return JobStatus(
            jobId=self.job_id,
            projectId=self.project_id,
            status=self.status,
            currentStage=self.current_stage,
            progress=round(
                sum(stage.progress for stage in self.stages.values()) / len(STAGE_ORDER),
                4,
            ),
            stages=stages,
            error=self.error,
        )

    def result(self) -> JobResult:
        return JobResult(
            projectId=self.project_id,
            videoPath=self.video_path,
            voiceoverPath=str(self.project_dir / "voiceover.wav"),
            subtitlesPath=str(self.project_dir / "subtitles.json"),
            duration=self.duration,
        )


class JobStore:
    def __init__(self, projects_dir: Path) -> None:
        self.projects_dir = projects_dir
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._jobs: Dict[str, JobRecord] = {}
        self._load_existing()

    def create(self, video_path: str, settings: JobSettings) -> JobRecord:
        with self._lock:
            project_id = new_project_id()
            job_id = new_job_id()
            project_dir = self.projects_dir / project_id
            project_dir.mkdir(parents=True, exist_ok=True)
            record = JobRecord(
                job_id=job_id,
                project_id=project_id,
                video_path=video_path,
                settings=settings,
                project_dir=project_dir,
            )
            self._jobs[job_id] = record
            self.save(record)
            return record

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            return self._require(job_id)

    def mutate(self, job_id: str, fn: Callable[[JobRecord], None]) -> JobRecord:
        """状態遷移を JobStore のロック下で一括実行し、永続化する。

        get() で取得したレコードを外で書き換えると、別スレッド（runner と
        cancel など）の更新と交錯し得るため、状態変更は本メソッド経由に集約する。
        """
        with self._lock:
            record = self._require(job_id)
            fn(record)
            self.save(record)
            return record

    def _require(self, job_id: str) -> JobRecord:
        try:
            return self._jobs[job_id]
        except KeyError:
            raise BackendError(
                code="JOB_NOT_FOUND",
                message=f"Job not found: {job_id}",
                status_code=404,
                retryable=False,
            )

    def save(self, record: JobRecord) -> None:
        with self._lock:
            record.project_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "version": 1,
                "projectId": record.project_id,
                "videoPath": record.video_path,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "duration": record.duration,
                "settings": model_to_dict(record.settings, by_alias=True),
                "job": {
                    "jobId": record.job_id,
                    "status": record.status.value,
                    "currentStage": record.current_stage.value if record.current_stage else None,
                    "error": model_to_dict(record.error) if record.error else None,
                    "stages": {
                        stage.name.value: {
                            "status": stage.status.value,
                            "progress": stage.progress,
                            "artifact": stage.artifact,
                        }
                        for stage in record.stages.values()
                    },
                },
            }
            # アトミック書き込み: 一時ファイルへ書いてから置換し、
            # 中断による project.json の破損（=再開時にジョブ消失）を防ぐ。
            manifest_path = record.project_dir / "project.json"
            tmp_path = record.project_dir / "project.json.tmp"
            tmp_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(manifest_path)

    def _load_existing(self) -> None:
        for manifest_path in self.projects_dir.glob("*/project.json"):
            record = self._load_manifest(manifest_path)
            if record:
                self._jobs[record.job_id] = record

    def _load_manifest(self, manifest_path: Path) -> Optional[JobRecord]:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            job = payload["job"]
            settings = JobSettings(**payload["settings"])
            stages_payload = job["stages"]
            stages = {}
            for name in STAGE_ORDER:
                stage_payload = stages_payload.get(name.value, {})
                stages[name] = StageRecord(
                    name=name,
                    status=StageState(stage_payload.get("status", StageState.pending.value)),
                    progress=float(stage_payload.get("progress", 0.0)),
                    artifact=stage_payload.get("artifact"),
                )
            error = ErrorBody(**job["error"]) if job.get("error") else None
            current_stage = job.get("currentStage")
            return JobRecord(
                job_id=job["jobId"],
                project_id=payload["projectId"],
                video_path=payload["videoPath"],
                settings=settings,
                project_dir=manifest_path.parent,
                status=JobState(job["status"]),
                current_stage=StageName(current_stage) if current_stage else None,
                stages=stages,
                error=error,
                duration=float(payload.get("duration", 0.0)),
            )
        except Exception as exc:
            # 破損/不整合のマニフェストは黙って捨てず警告する（失敗を握りつぶさない）。
            # 当該ファイルは保持したまま読み込み対象から除外し、他ジョブの再開を妨げない。
            print(
                f"[reverb] failed to load manifest {manifest_path}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return None

    def all(self) -> List[JobRecord]:
        with self._lock:
            return list(self._jobs.values())
