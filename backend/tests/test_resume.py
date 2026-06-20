from pathlib import Path

from main import create_app


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
