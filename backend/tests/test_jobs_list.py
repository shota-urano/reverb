from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from core.job_store import JobStore
from main import create_app
from services.job_service import JobService


def test_list_jobs_loads_manifests_in_reverse_created_at_order(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        project_id="p_old",
        job_id="j_old",
        created_at="2026-06-19T10:00:00+00:00",
        language="en",
    )
    _write_manifest(
        tmp_path,
        project_id="p_new",
        job_id="j_new",
        created_at="2026-06-21T10:00:00+00:00",
        language=None,
    )
    store = JobStore(tmp_path)
    service = _service_for_store(tmp_path, store)

    response = service.list_jobs()

    assert [item.projectId for item in response.items] == ["p_new", "p_old"]
    assert {record.project_id for record in store.list_records()} == {"p_old", "p_new"}


def test_list_jobs_includes_language_when_configured_and_null_when_auto(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        project_id="p_auto",
        job_id="j_auto",
        created_at="2026-06-19T10:00:00+00:00",
        language=None,
    )
    _write_manifest(
        tmp_path,
        project_id="p_en",
        job_id="j_en",
        created_at="2026-06-20T10:00:00+00:00",
        language="en",
        current_stage="translate",
    )
    service = _service_for_store(tmp_path, JobStore(tmp_path))

    items = service.list_jobs().items

    assert items[0].projectId == "p_en"
    assert items[0].language == "en"
    assert items[0].currentStage == "translate"
    assert items[1].projectId == "p_auto"
    assert items[1].language is None
    assert items[1].currentStage is None


def test_list_jobs_survives_restart(tmp_path: Path) -> None:
    first_store = JobStore(tmp_path)
    created = first_store.create("/tmp/input.mp4", _settings(language="en"))
    first_created_at = created.created_at

    restarted_store = JobStore(tmp_path)
    restarted = restarted_store.get(created.job_id)

    assert restarted.created_at == first_created_at
    assert restarted_store.list_records()[0].project_id == created.project_id


def test_save_preserves_original_created_at(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    created = store.create("/tmp/input.mp4", _settings(language="en"))
    manifest_path = tmp_path / created.project_id / "project.json"
    original_created_at = json.loads(manifest_path.read_text(encoding="utf-8"))["createdAt"]

    def apply(record) -> None:
        record.duration = 42.0

    store.mutate(created.job_id, apply)

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["createdAt"] == original_created_at
    assert saved["duration"] == 42.0


def test_get_jobs_returns_persisted_projects(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        project_id="p_old",
        job_id="j_old",
        created_at="2026-06-19T10:00:00+00:00",
        language="en",
        status="done",
        duration=12.5,
        video_path="/tmp/old.mp4",
    )
    _write_manifest(
        tmp_path,
        project_id="p_new",
        job_id="j_new",
        created_at="2026-06-21T10:00:00+00:00",
        language=None,
        status="running",
        current_stage="tts",
        duration=30.0,
        video_path="/tmp/new.mp4",
    )
    client = TestClient(create_app(projects_dir=tmp_path))

    response = client.get("/jobs")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "projectId": "p_new",
                "jobId": "j_new",
                "status": "running",
                "createdAt": "2026-06-21T10:00:00+00:00",
                "duration": 30.0,
                "videoPath": "/tmp/new.mp4",
                "language": None,
                "currentStage": "tts",
                "hasThumbnail": False,
            },
            {
                "projectId": "p_old",
                "jobId": "j_old",
                "status": "done",
                "createdAt": "2026-06-19T10:00:00+00:00",
                "duration": 12.5,
                "videoPath": "/tmp/old.mp4",
                "language": "en",
                "currentStage": None,
                "hasThumbnail": False,
            },
        ]
    }


def _service_for_store(tmp_path: Path, store: JobStore) -> JobService:
    app = create_app(projects_dir=tmp_path)
    app.state.job_store = store
    app.state.job_service.store = store
    app.state.job_service.runner.store = store
    return app.state.job_service


def _write_manifest(
    projects_dir: Path,
    *,
    project_id: str,
    job_id: str,
    created_at: str,
    language: str | None,
    status: str = "queued",
    current_stage: str | None = None,
    duration: float = 0.0,
    video_path: str = "/tmp/input.mp4",
) -> None:
    project_dir = projects_dir / project_id
    project_dir.mkdir(parents=True)
    payload = {
        "version": 1,
        "projectId": project_id,
        "videoPath": video_path,
        "createdAt": created_at,
        "duration": duration,
        "settings": _settings_payload(language=language),
        "job": {
            "jobId": job_id,
            "status": status,
            "currentStage": current_stage,
            "error": None,
            "stages": {
                name: {"status": "pending", "progress": 0.0, "artifact": None}
                for name in ["extract", "transcribe", "translate", "subtitle", "tts", "mix"]
            },
        },
    }
    (project_dir / "project.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _settings(language: str | None = None):
    from schemas.settings import JobSettings

    return JobSettings(**_settings_payload(language=language))


def _settings_payload(language: str | None) -> dict:
    return {
        "stt": {"model": "large-v3", "language": language},
        "translate": {"model": "qwen3:30b"},
        "tts": {"speakerId": 13, "styleId": 0},
        "mix": {"jaVolume": 1.0, "originalVolume": 0.08},
    }
