from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI

from adapters.ffmpeg import FFmpegAdapter
from adapters.ollama import OllamaAdapter
from adapters.voicevox import VoicevoxAdapter
from adapters.whisper_mlx import WhisperMLXAdapter
from api import jobs_router, meta_router
from core.config import BackendConfig
from core.errors import install_error_handlers
from core.job_store import JobStore
from services.job_service import JobService


def create_app(projects_dir: Optional[Path] = None) -> FastAPI:
    config = BackendConfig()
    if projects_dir is not None:
        config = config.with_projects_dir(projects_dir)

    app = FastAPI(title="Reverb Backend", version=config.version)
    app.state.config = config
    app.state.ffmpeg = FFmpegAdapter(config.ffmpeg_bin, config.ffprobe_bin)
    app.state.whisper = WhisperMLXAdapter()
    app.state.ollama = OllamaAdapter(
        config.ollama_base_url,
        config.dependency_timeout_seconds,
    )
    app.state.voicevox = VoicevoxAdapter(
        config.voicevox_base_url,
        config.dependency_timeout_seconds,
    )
    app.state.job_store = JobStore(config.projects_dir)
    app.state.job_service = JobService(config, app.state.job_store, app.state.ffmpeg)
    app.include_router(meta_router)
    app.include_router(jobs_router)
    install_error_handlers(app)
    return app


def main() -> None:
    app = create_app()
    config = app.state.config
    server_config = uvicorn.Config(
        app,
        host=config.host,
        port=config.port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(server_config)
    app.state.server = server

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((config.host, config.port))
    sock.listen()
    port = sock.getsockname()[1]

    _start_parent_monitor(os.getppid(), server)
    print(
        json.dumps(
            {
                "event": "ready",
                "baseURL": f"http://{config.host}:{port}",
                "pid": os.getpid(),
                "version": config.version,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )
    server.run(sockets=[sock])


def _start_parent_monitor(initial_ppid: int, server: uvicorn.Server) -> None:
    def monitor() -> None:
        while not server.should_exit:
            if os.getppid() != initial_ppid:
                server.should_exit = True
                break
            time.sleep(1.0)

    thread = threading.Thread(target=monitor, name="parent-process-monitor", daemon=True)
    thread.start()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
