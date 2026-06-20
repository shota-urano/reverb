from __future__ import annotations

from queue import Empty

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import StreamingResponse

from core.serialization import model_to_json
from schemas.enums import JobState
from schemas.jobs import CreateJobRequest, CreateJobResponse, JobResult, JobStatus

router = APIRouter(prefix="/jobs")


@router.post("", response_model=CreateJobResponse)
def create_job(
    payload: CreateJobRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> CreateJobResponse:
    response = request.app.state.job_service.create_job(payload.videoPath, payload.settings)
    background_tasks.add_task(request.app.state.job_service.run_job, response.jobId)
    return response


@router.get("/{job_id}", response_model=JobStatus)
def get_job(job_id: str, request: Request) -> JobStatus:
    return request.app.state.job_service.get_job(job_id)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict:
    request.app.state.job_service.cancel_job(job_id)
    return {}


@router.get("/{job_id}/result", response_model=JobResult)
def job_result(job_id: str, request: Request) -> JobResult:
    return request.app.state.job_service.result(job_id)


@router.get("/{job_id}/events")
def job_events(job_id: str, request: Request) -> StreamingResponse:
    service = request.app.state.job_service
    queue = service.subscribe(job_id)

    def stream():
        try:
            while True:
                try:
                    snapshot = queue.get(timeout=30)
                except Empty:
                    yield ": keep-alive\n\n"
                    continue
                if snapshot.status == JobState.done:
                    result = service.result(job_id)
                    yield (
                        "event: done\n"
                        f'data: {{"projectId":"{result.projectId}",'
                        f'"result":{model_to_json(result)}}}\n\n'
                    )
                    break
                yield ("event: progress\n" f"data: {model_to_json(snapshot, by_alias=True)}\n\n")
                if snapshot.status in (JobState.failed, JobState.canceled):
                    break
        finally:
            service.unsubscribe(job_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream")
