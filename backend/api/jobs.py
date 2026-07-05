from __future__ import annotations

from queue import Empty

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from core.serialization import model_to_json
from schemas.enums import JobState
from schemas.jobs import (
    CreateJobRequest,
    CreateJobResponse,
    EmptyResponse,
    JobListResponse,
    JobResult,
    JobStatus,
)

router = APIRouter(prefix="/jobs")


@router.get("", response_model=JobListResponse)
def list_jobs(request: Request) -> JobListResponse:
    return request.app.state.job_service.list_jobs()


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


@router.post("/{job_id}/resume", response_model=CreateJobResponse)
def resume_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
) -> CreateJobResponse:
    response = request.app.state.job_service.resume_job(job_id)
    background_tasks.add_task(request.app.state.job_service.run_job, job_id)
    return response


@router.delete("/{job_id}", status_code=200, response_model=EmptyResponse)
def delete_job(job_id: str, request: Request) -> EmptyResponse:
    request.app.state.job_service.delete_job(job_id)
    return EmptyResponse()


@router.get("/{job_id}/result", response_model=JobResult)
def job_result(job_id: str, request: Request) -> JobResult:
    return request.app.state.job_service.result(job_id)


@router.get("/{job_id}/thumbnail")
def job_thumbnail(job_id: str, request: Request) -> FileResponse:
    path = request.app.state.job_service.thumbnail_path(job_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(path, media_type="image/jpeg")


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
                if snapshot is None:
                    break
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
