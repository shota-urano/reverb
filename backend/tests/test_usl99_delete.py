from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.errors import BackendError
from core.job_store import JobStore
from main import create_app
from schemas.enums import JobState
from schemas.settings import default_job_settings


def test_delete_job_removes_it_from_list_and_deletes_project_dir(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    _stub_empty_pipeline(app)
    client = TestClient(app)

    created_response = client.post("/jobs", json={"videoPath": "/tmp/input.mp4"})
    assert created_response.status_code == 200
    created = created_response.json()
    project_dir = tmp_path / created["projectId"]
    assert project_dir.exists()

    response = client.delete(f"/jobs/{created['jobId']}")

    assert response.status_code == 200
    assert response.json() == {}
    assert client.get("/jobs").json() == {"items": []}
    assert not project_dir.exists()


def test_delete_running_job_returns_409(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    created = app.state.job_service.create_job("/tmp/input.mp4", None)
    app.state.job_store.mutate(
        created.jobId,
        lambda record: setattr(record, "status", JobState.running),
    )

    response = TestClient(app).delete(f"/jobs/{created.jobId}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_RUNNING"


def test_delete_queued_job_returns_409(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    created = app.state.job_service.create_job("/tmp/input.mp4", None)

    response = TestClient(app).delete(f"/jobs/{created.jobId}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_RUNNING"


def test_delete_missing_job_returns_404(tmp_path: Path) -> None:
    response = TestClient(create_app(projects_dir=tmp_path)).delete("/jobs/j_missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_delete_job_openapi_registers_empty_response_schema(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)

    delete_operation = app.openapi()["paths"]["/jobs/{job_id}"]["delete"]

    schema = delete_operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"] == "#/components/schemas/EmptyResponse"


def test_delete_job_twice_returns_404(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    _stub_empty_pipeline(app)
    client = TestClient(app)
    created = client.post("/jobs", json={"videoPath": "/tmp/input.mp4"}).json()

    first_response = client.delete(f"/jobs/{created['jobId']}")
    second_response = client.delete(f"/jobs/{created['jobId']}")

    assert first_response.status_code == 200
    assert second_response.status_code == 404
    assert second_response.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_store_delete_rejects_project_dir_outside_projects_dir(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    store = JobStore(projects_dir)
    app = create_app(projects_dir=projects_dir)
    record = store.create("/tmp/input.mp4", default_job_settings(app.state.config))

    record.status = JobState.done
    record.project_dir = outside_dir

    with pytest.raises(BackendError) as exc_info:
        store.delete(record.job_id)

    assert exc_info.value.code == "INVALID_PATH"
    assert exc_info.value.status_code == 400
    assert outside_dir.exists()


def test_store_delete_keeps_record_when_rmtree_permission_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(projects_dir=tmp_path)
    store = JobStore(tmp_path)
    record = store.create("/tmp/input.mp4", default_job_settings(app.state.config))
    record.status = JobState.done

    def raise_permission_error(_path: Path) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(shutil, "rmtree", raise_permission_error)

    with pytest.raises(PermissionError):
        store.delete(record.job_id)

    assert record.job_id in store._jobs


def test_store_delete_swallows_missing_project_dir_and_removes_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(projects_dir=tmp_path)
    store = JobStore(tmp_path)
    record = store.create("/tmp/input.mp4", default_job_settings(app.state.config))
    record.status = JobState.done

    def raise_file_not_found_error(_path: Path) -> None:
        raise FileNotFoundError("already gone")

    monkeypatch.setattr(shutil, "rmtree", raise_file_not_found_error)

    store.delete(record.job_id)

    assert record.job_id not in store._jobs


def test_save_deleted_record_does_not_recreate_project_manifest(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    store = JobStore(tmp_path)
    record = store.create("/tmp/input.mp4", default_job_settings(app.state.config))
    record.status = JobState.done

    store.delete(record.job_id)
    store.save(record)

    assert not record.project_dir.exists()
    assert not (record.project_dir / "project.json").exists()


def test_save_created_record_writes_project_manifest(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    store = JobStore(tmp_path)
    record = store.create("/tmp/input.mp4", default_job_settings(app.state.config))
    manifest_path = record.project_dir / "project.json"
    manifest_path.unlink()

    store.save(record)

    assert manifest_path.exists()


def _stub_empty_pipeline(app) -> None:
    app.state.ffmpeg.probe = lambda _: (True, 12.5)
    app.state.ffmpeg.extract = lambda _, out_path, _options, progress_cb: (
        progress_cb(0.5),
        Path(out_path).write_bytes(b"wav"),
        progress_cb(1.0),
    )
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
