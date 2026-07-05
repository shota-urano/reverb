from pathlib import Path

from fastapi.testclient import TestClient

from core.errors import ErrorBody
from main import create_app
from schemas.enums import JobState, StageName, StageState


def test_store_loads_existing_manifest_for_resume(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    service = app.state.job_service

    created = service.create_job("/tmp/input.mp4", None)
    first_snapshot = service.get_job(created.jobId)

    resumed_app = create_app(projects_dir=tmp_path)
    resumed = resumed_app.state.job_service.get_job(created.jobId)

    assert resumed.projectId == first_snapshot.projectId
    assert resumed.status == first_snapshot.status
    assert [stage.name for stage in resumed.stages] == [
        "extract",
        "transcribe",
        "translate",
        "subtitle",
        "tts",
        "mix",
    ]
    assert Path(tmp_path, resumed.projectId, "project.json").exists()


def test_resume_failed_job_runs_remaining_stages(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    _stub_empty_pipeline(app)
    client = TestClient(app)
    created = client.post("/jobs", json={"videoPath": "/tmp/input.mp4"}).json()

    mix_calls = 0

    def fail_at_mix(record) -> None:
        record.status = JobState.failed
        record.current_stage = StageName.mix
        record.stages[StageName.mix].status = StageState.failed
        record.stages[StageName.mix].progress = 0.0
        record.error = ErrorBody(
            code="MIX_FAILED",
            stage="mix",
            message="mix failed",
            retryable=True,
        )

    def mix_voiceover(
        _audio,
        _cue_inputs,
        out_path,
        _duration,
        _ja_volume,
        _original_volume,
    ) -> None:
        nonlocal mix_calls
        mix_calls += 1
        Path(out_path).write_bytes(b"voiceover-resumed")

    app.state.job_store.mutate(created["jobId"], fail_at_mix)
    app.state.ffmpeg.extract = lambda *_args: (_ for _ in ()).throw(
        AssertionError("completed extract stage was rerun")
    )
    app.state.ffmpeg.mix_voiceover = mix_voiceover

    response = client.post(f"/jobs/{created['jobId']}/resume")

    assert response.status_code == 200
    assert response.json() == {
        "jobId": created["jobId"],
        "projectId": created["projectId"],
        "status": "queued",
    }
    status = client.get(f"/jobs/{created['jobId']}").json()
    assert status["status"] == "done"
    assert status["error"] is None
    assert mix_calls == 1


def test_resume_done_job_returns_409(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    created = app.state.job_service.create_job("/tmp/input.mp4", None)
    app.state.job_store.mutate(
        created.jobId,
        lambda record: setattr(record, "status", JobState.done),
    )

    response = TestClient(app).post(f"/jobs/{created.jobId}/resume")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_ALREADY_DONE"


def test_resume_running_job_returns_409(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    created = app.state.job_service.create_job("/tmp/input.mp4", None)
    app.state.job_store.mutate(
        created.jobId,
        lambda record: setattr(record, "status", JobState.running),
    )

    response = TestClient(app).post(f"/jobs/{created.jobId}/resume")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_RUNNING"


def test_resume_missing_job_returns_404(tmp_path: Path) -> None:
    response = TestClient(create_app(projects_dir=tmp_path)).post("/jobs/j_missing/resume")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


def _stub_empty_pipeline(app) -> None:
    app.state.ffmpeg.probe = lambda _: (True, 12.5)
    app.state.ffmpeg.extract = lambda _, out_path, _options, progress_cb: (
        progress_cb(0.5),
        Path(out_path).write_bytes(b"wav"),
        progress_cb(1.0),
    )
    app.state.ffmpeg.extract_thumbnail = lambda *_args: None
    app.state.ffmpeg.mix_voiceover = (
        lambda _audio, _cue_inputs, out_path, _duration, _ja_volume, _original_volume: Path(
            out_path
        ).write_bytes(b"voiceover")
    )
    app.state.whisper.transcribe = lambda _audio, _model, language, _options, progress_cb: (
        progress_cb(0.0),
        progress_cb(1.0),
        (language, []),
    )[-1]
    app.state.ollama.generate_glossary = lambda *_args: []
    app.state.ollama.warm_up = lambda *_args: None
    app.state.ollama.translate = lambda *_args: []
    app.state.ollama.polish = lambda *_args: []
