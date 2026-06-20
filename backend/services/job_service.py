from __future__ import annotations

from queue import Queue
from threading import RLock
from typing import Dict, List, Optional

from core.config import BackendConfig
from core.errors import BackendError
from core.job_store import JobRecord, JobStore
from pipeline.extract import AudioExtractor, ExtractStage
from pipeline.stage import Stage
from pipeline.stub_stages import StubStage
from pipeline.transcribe import Transcriber, TranscribeStage
from pipeline.translate import Translator, TranslateStage
from schemas.enums import JobState, StageState
from schemas.enums import StageName
from schemas.jobs import CreateJobResponse, JobResult, JobStatus
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
    ) -> None:
        self.config = config
        self.store = store
        self._lock = RLock()
        self._subscribers: Dict[str, List[Queue]] = {}
        self.runner = PipelineRunner(
            config,
            store,
            build_pipeline_stages(ffmpeg, whisper, ollama),
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
) -> List[Stage]:
    return [
        ExtractStage(ffmpeg),
        TranscribeStage(whisper),
        TranslateStage(translator),
        StubStage(StageName.subtitle, "subtitles.json"),
        StubStage(StageName.tts, "tts/cue_0000.wav"),
        StubStage(StageName.mix, "voiceover.wav"),
    ]
