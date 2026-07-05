from __future__ import annotations

from pathlib import Path
from queue import Queue
from threading import RLock
from typing import Dict, List, Optional

from core.config import BackendConfig
from core.artifacts import THUMBNAIL_PATH
from core.errors import BackendError
from core.job_store import JobRecord, JobStore
from pipeline.extract import AudioExtractor, ExtractStage
from pipeline.mix import MixStage
from pipeline.stage import Stage
from pipeline.subtitle import SubtitleStage
from pipeline.transcribe import Transcriber, TranscribeStage
from pipeline.tts import TtsStage, TtsSynthesizer
from pipeline.translate import Translator, TranslateStage
from schemas.enums import JobState, StageState
from schemas.jobs import CreateJobResponse, JobListResponse, JobResult, JobStatus, JobSummary
from schemas.settings import JobSettings, default_job_settings
from services.pipeline_runner import PipelineRunner


class JobService:
    def __init__(
        self,
        config: BackendConfig,
        store: JobStore,
        ffmpeg: AudioExtractor,
        whisper: Transcriber,
        ollama: Translator,
        tts: TtsSynthesizer,
    ) -> None:
        self.config = config
        self.store = store
        self._lock = RLock()
        self._subscribers: Dict[str, List[Queue]] = {}
        self.runner = PipelineRunner(
            config,
            store,
            build_pipeline_stages(ffmpeg, whisper, ollama, tts),
            self._notify,
        )

    def create_job(self, video_path: str, settings: Optional[JobSettings]) -> CreateJobResponse:
        record = self.store.create(video_path, settings or default_job_settings(self.config))
        return CreateJobResponse(
            jobId=record.job_id,
            projectId=record.project_id,
            status=record.status,
        )

    def run_job(self, job_id: str) -> None:
        self.runner.run(self.store.get(job_id))

    def get_job(self, job_id: str) -> JobStatus:
        return self.store.get(job_id).snapshot()

    def list_jobs(self) -> JobListResponse:
        records = sorted(
            self.store.list_records(),
            key=lambda record: record.created_at,
            reverse=True,
        )
        summaries = [
            JobSummary(
                projectId=record.project_id,
                jobId=record.job_id,
                status=record.status,
                createdAt=record.created_at.isoformat(),
                duration=record.duration,
                videoPath=record.video_path,
                language=record.settings.stt.language if record.settings.stt else None,
                currentStage=record.current_stage,
                hasThumbnail=(record.project_dir / THUMBNAIL_PATH).exists(),
            )
            for record in records
        ]
        return JobListResponse(items=summaries)

    def cancel_job(self, job_id: str) -> None:
        changed = False

        def apply(record: JobRecord) -> None:
            nonlocal changed
            if record.status in (JobState.done, JobState.failed, JobState.canceled):
                return
            record.status = JobState.canceled
            record.current_stage = None
            for stage in record.stages.values():
                if stage.status in (StageState.pending, StageState.running):
                    stage.status = StageState.canceled
            changed = True

        record = self.store.mutate(job_id, apply)
        if changed:
            self._notify(record)

    def resume_job(self, job_id: str) -> CreateJobResponse:
        def apply(record: JobRecord) -> None:
            if record.status == JobState.done:
                raise BackendError(
                    code="JOB_ALREADY_DONE",
                    message=f"Job is already done: {job_id}",
                    status_code=409,
                    retryable=False,
                )
            if record.status in (JobState.running, JobState.queued):
                raise BackendError(
                    code="JOB_RUNNING",
                    message=f"Job is running: {job_id}",
                    status_code=409,
                    retryable=True,
                )
            record.status = JobState.queued
            record.error = None

        record = self.store.mutate(job_id, apply)
        return CreateJobResponse(
            jobId=record.job_id,
            projectId=record.project_id,
            status=record.status,
        )

    def delete_job(self, job_id: str) -> None:
        self.store.delete(job_id)
        with self._lock:
            queues = self._subscribers.pop(job_id, [])
        for queue in queues:
            queue.put(None)

    def result(self, job_id: str) -> JobResult:
        record = self.store.get(job_id)
        if record.status != JobState.done:
            raise BackendError(
                code="JOB_NOT_DONE",
                message=f"Job is not done: {job_id}",
                status_code=409,
                retryable=True,
            )
        return record.result()

    def thumbnail_path(self, job_id: str) -> Optional[Path]:
        record = self.store.get(job_id)
        path = record.project_dir / THUMBNAIL_PATH
        if path.exists():
            return path
        return None

    def subscribe(self, job_id: str) -> Queue:
        self.store.get(job_id)
        queue: Queue = Queue()
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(queue)
        queue.put(self.get_job(job_id))
        return queue

    def unsubscribe(self, job_id: str, queue: Queue) -> None:
        with self._lock:
            queues = self._subscribers.get(job_id, [])
            if queue in queues:
                queues.remove(queue)

    def _notify(self, record: JobRecord) -> None:
        snapshot = record.snapshot()
        with self._lock:
            queues = list(self._subscribers.get(record.job_id, []))
        for queue in queues:
            queue.put(snapshot)


def build_pipeline_stages(
    ffmpeg: AudioExtractor,
    whisper: Transcriber,
    translator: Translator,
    tts: TtsSynthesizer,
) -> List[Stage]:
    return [
        ExtractStage(ffmpeg),
        TranscribeStage(whisper),
        TranslateStage(translator),
        SubtitleStage(),
        TtsStage(tts),
        MixStage(ffmpeg, tts),
    ]
