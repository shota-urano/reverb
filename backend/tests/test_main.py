import json
import os
import re
import subprocess
import sys
import threading

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
        handshake = json.loads(line)

        assert handshake["event"] == "ready"
        assert re.fullmatch(r"http://127\.0\.0\.1:\d+", handshake["baseURL"])
        assert handshake["pid"] == process.pid
        assert handshake["version"] == BackendConfig().version
    finally:
        process.terminate()
        process.wait(timeout=5)
