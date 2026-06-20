import json
import os
import re
import subprocess
import sys


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
        line = process.stdout.readline().strip()
        handshake = json.loads(line)

        assert handshake["event"] == "ready"
        assert re.fullmatch(r"http://127\.0\.0\.1:\d+", handshake["baseURL"])
        assert handshake["pid"] == process.pid
        assert handshake["version"] == "0.6.0"
    finally:
        process.terminate()
        process.wait(timeout=5)
