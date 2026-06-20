from __future__ import annotations

from typing import Callable, Iterable

from core.config import BackendConfig
from core.errors import ErrorBody
from core.job_store import JobRecord, JobStore
from pipeline.stage import PipelineContext, Stage
from schemas.enums import JobState, StageState


class PipelineRunner:
    def __init__(
        self,
        config: BackendConfig,
        store: JobStore,
        stages: Iterable[Stage],
        notify: Callable[[JobRecord], None],
    ) -> None:
        self.config = config
        self.store = store
        self.stages = list(stages)
        self.notify = notify

    def run(self, record: JobRecord) -> None:
        if record.status == JobState.canceled:
            return
        record.status = JobState.running
        record.error = None
        self.store.save(record)
        self.notify(record)

        context = PipelineContext(
            config=self.config,
            job=record,
            project_dir=record.project_dir,
        )
        try:
            for stage in self.stages:
                stage_record = record.stages[stage.name]
                if stage_record.status == StageState.done:
                    continue
                if record.status == JobState.canceled:
                    self._mark_pending_canceled(record)
                    return
                record.current_stage = stage.name
                stage_record.status = StageState.running
                stage_record.progress = 0.0
                self.store.save(record)
                self.notify(record)

                artifact = stage.run(context)

                # ステージ完了直後にキャンセル要求があれば done で上書きしない。
                if record.status == JobState.canceled:
                    self._mark_pending_canceled(record)
                    return

                stage_record.status = StageState.done
                stage_record.progress = 1.0
                stage_record.artifact = artifact
                self.store.save(record)
                self.notify(record)
            # 最終ステージ実行中のキャンセルを done で上書きしないよう最後に再確認。
            if record.status == JobState.canceled:
                self._mark_pending_canceled(record)
                return
            record.current_stage = None
            record.status = JobState.done
            record.duration = 0.0
            self.store.save(record)
            self.notify(record)
        except Exception as exc:
            stage_name = record.current_stage.value if record.current_stage else None
            if record.current_stage:
                record.stages[record.current_stage].status = StageState.failed
            record.status = JobState.failed
            record.error = ErrorBody(
                code="PIPELINE_STAGE_FAILED",
                stage=stage_name,
                message=str(exc),
                retryable=True,
            )
            self.store.save(record)
            self.notify(record)

    def _mark_pending_canceled(self, record: JobRecord) -> None:
        for stage in record.stages.values():
            if stage.status in (StageState.pending, StageState.running):
                stage.status = StageState.canceled
        record.current_stage = None
        self.store.save(record)
        self.notify(record)
