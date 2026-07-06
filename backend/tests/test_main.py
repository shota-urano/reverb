import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import main as backend_main
from core.config import BackendConfig


def _read_line_with_timeout(stream, timeout: float) -> str:
    """ハンドシェイク待ちで無限ブロックしないよう、別スレッドで bounded read する。"""
    result = {}

    def reader() -> None:
        result["line"] = stream.readline()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(timeout)
    assert "line" in result, "Timed out waiting for ready handshake"
    return result["line"].strip()


def test_prepend_existing_directories_to_path_places_directory_first(tmp_path: Path) -> None:
    binary_dir = tmp_path / "bundled-bin"
    binary_dir.mkdir()
    original_path = os.pathsep.join(["/usr/bin", "/bin"])

    result = backend_main._prepend_existing_directories_to_path(
        original_path,
        [binary_dir],
    )

    assert result == os.pathsep.join([str(binary_dir), original_path])


def test_create_app_leaves_path_unchanged_for_relative_binary_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_path = os.pathsep.join(["/usr/bin", "/bin"])
    monkeypatch.setenv("PATH", original_path)
    monkeypatch.setenv("REVERB_FFMPEG_BIN", "ffmpeg")
    monkeypatch.setenv("REVERB_FFPROBE_BIN", "ffprobe")

    backend_main.create_app(projects_dir=tmp_path / "projects")

    assert os.environ["PATH"] == original_path


def test_prepend_existing_directories_to_path_does_not_duplicate_leading_directory(
    tmp_path: Path,
) -> None:
    binary_dir = tmp_path / "bundled-bin"
    binary_dir.mkdir()
    original_path = os.pathsep.join([str(binary_dir), "/usr/bin", "/bin"])

    result = backend_main._prepend_existing_directories_to_path(
        original_path,
        [binary_dir],
    )

    assert result == original_path


def test_prepend_existing_directories_to_path_skips_missing_directory(tmp_path: Path) -> None:
    original_path = os.pathsep.join(["/usr/bin", "/bin"])

    result = backend_main._prepend_existing_directories_to_path(
        original_path,
        [tmp_path / "missing-bin"],
    )

    assert result == original_path


def test_create_app_prepends_distinct_configured_binary_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ffmpeg_dir = tmp_path / "ffmpeg-bin"
    ffprobe_dir = tmp_path / "ffprobe-bin"
    ffmpeg_dir.mkdir()
    ffprobe_dir.mkdir()
    projects_dir = tmp_path / "projects"
    original_path = os.pathsep.join(["/usr/bin", "/bin"])
    monkeypatch.setenv("PATH", original_path)
    monkeypatch.setenv("REVERB_FFMPEG_BIN", str(ffmpeg_dir / "ffmpeg"))
    monkeypatch.setenv("REVERB_FFPROBE_BIN", str(ffprobe_dir / "ffprobe"))

    app = backend_main.create_app(projects_dir=projects_dir)

    assert os.environ["PATH"].split(os.pathsep) == [
        str(ffmpeg_dir),
        str(ffprobe_dir),
        "/usr/bin",
        "/bin",
    ]
    assert app.state.config.projects_dir == projects_dir


def test_prepend_existing_directories_to_path_deduplicates_candidates(tmp_path: Path) -> None:
    binary_dir = tmp_path / "bundled-bin"
    binary_dir.mkdir()

    result = backend_main._prepend_existing_directories_to_path(
        "/usr/bin",
        [binary_dir, binary_dir],
    )

    assert result.split(os.pathsep) == [str(binary_dir), "/usr/bin"]


def test_main_prints_ready_handshake_and_serves_health() -> None:
    process = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        line = _read_line_with_timeout(process.stdout, timeout=15)
        if not line:
            process.wait(timeout=5)
            stderr = process.stderr.read() if process.stderr is not None else ""
            if "PermissionError" in stderr and "Operation not permitted" in stderr:
                pytest.skip("Socket bind is not permitted in this sandbox.")
        handshake = json.loads(line)

        assert handshake["event"] == "ready"
        assert re.fullmatch(r"http://127\.0\.0\.1:\d+", handshake["baseURL"])
        assert handshake["pid"] == process.pid
        assert handshake["version"] == BackendConfig().version
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
