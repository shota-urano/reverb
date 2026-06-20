from pathlib import Path

from fastapi.testclient import TestClient

from main import create_app


def test_health_returns_dependency_availability_without_raising() -> None:
    app = create_app()
    app.state.ffmpeg.available = lambda: False
    app.state.whisper.available = lambda: False
    app.state.ollama.ping = lambda: False
    app.state.voicevox.ping = lambda: False

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": app.state.config.version,
        "dependencies": {
            "ffmpeg": False,
            "mlx_whisper": False,
            "ollama": False,
            "voicevox": False,
        },
    }


def test_models_and_speakers_fall_back_to_empty_lists_when_engines_are_down() -> None:
    app = create_app()
    app.state.ollama.list_models = lambda: []
    app.state.voicevox.list_speakers = lambda: []

    client = TestClient(app)

    assert client.get("/models").json() == {
        "default": app.state.config.default_translate_model,
        "models": [],
    }
    assert client.get("/speakers").json() == {
        "default": {
            "speakerId": app.state.config.default_speaker_id,
            "name": app.state.config.default_speaker_name,
            "styleId": app.state.config.default_style_id,
        },
        "speakers": [],
    }


def test_job_create_runs_stub_pipeline_to_done(tmp_path: Path) -> None:
    app = create_app(projects_dir=tmp_path)
    client = TestClient(app)

    response = client.post("/jobs", json={"videoPath": "/tmp/input.mp4"})

    assert response.status_code == 200
    created = response.json()
    assert created["status"] == "queued"

    status = client.get(f"/jobs/{created['jobId']}").json()
    assert status["jobId"] == created["jobId"]
    assert status["projectId"] == created["projectId"]
    assert status["status"] == "done"
    assert status["currentStage"] is None
    assert status["progress"] == 1.0
    assert [stage["name"] for stage in status["stages"]] == [
        "extract",
        "transcribe",
        "translate",
        "subtitle",
        "tts",
        "mix",
    ]
    assert all(stage["status"] == "done" for stage in status["stages"])

    result = client.get(f"/jobs/{created['jobId']}/result")
    assert result.status_code == 200
    assert result.json()["voiceoverPath"].endswith("voiceover.wav")
    assert result.json()["subtitlesPath"].endswith("subtitles.json")


def test_missing_job_uses_unified_error_body() -> None:
    response = TestClient(create_app()).get("/jobs/j_missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "JOB_NOT_FOUND",
            "stage": None,
            "message": "Job not found: j_missing",
            "retryable": False,
        }
    }
