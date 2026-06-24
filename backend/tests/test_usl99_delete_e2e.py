"""USL-99 DELETE /jobs/{id} の実プロセス E2E。

TestClient（in-process）ではなく、実際に `main.py` をサブプロセスで起動し、
ready ハンドシェイクで baseURL を受け取って **実 HTTP** で削除フローを検証する
（フロント Swift アプリと同じ起動・通信経路をなぞる E2E）。

- 保存先は REVERB_PROJECTS_DIR で一時ディレクトリに隔離し、実ユーザーデータ
  （~/Library/Application Support/Reverb/projects）には一切触れない。
- 外部エンジン（ffmpeg/whisper/ollama/voicevox）に依存しないよう、作成直後に
  cancel して終端状態（canceled/failed）へ落としてから削除する。

running/queued の 409・パストラバーサル拒否といった分岐は in-process の
test_usl99_delete.py で決定的に検証済み。本 E2E は実プロセス経由の正常系
（作成→一覧反映→削除→一覧/ディスクから消える→冪等 404）を担保する。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MAIN_PY = BACKEND_ROOT / "main.py"

TERMINAL_STATES = {"canceled", "failed", "done"}


def _request(method: str, url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, (json.loads(body) if body else {})


def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, (json.loads(body) if body else {})


def _read_handshake(proc: subprocess.Popen, timeout: float = 30.0) -> str:
    """ready ハンドシェイク行を読み、baseURL を返す。"""
    deadline = time.time() + timeout
    assert proc.stdout is not None
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise RuntimeError(f"sidecar exited early: code={proc.returncode}")
            continue
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") == "ready" and payload.get("baseURL"):
            return payload["baseURL"]
    raise RuntimeError("handshake timeout")


@pytest.fixture()
def sidecar(tmp_path: Path):
    projects_dir = tmp_path / "projects"
    env = dict(os.environ)
    env["REVERB_PROJECTS_DIR"] = str(projects_dir)
    env["REVERB_PORT"] = "0"  # OS 任意ポート（ハンドシェイクで受け取る）
    proc = subprocess.Popen(
        [sys.executable, str(MAIN_PY)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    try:
        base_url = _read_handshake(proc)
        yield base_url, projects_dir
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _wait_terminal(base_url: str, job_id: str, timeout: float = 15.0) -> str:
    deadline = time.time() + timeout
    last = "?"
    while time.time() < deadline:
        status, body = _request("GET", f"{base_url}/jobs/{job_id}")
        assert status == 200
        last = body["status"]
        if last in TERMINAL_STATES:
            return last
        time.sleep(0.2)
    raise AssertionError(f"job did not reach terminal state (last={last})")


def test_delete_flow_over_real_http(sidecar) -> None:
    base_url, projects_dir = sidecar

    # health
    status, health = _request("GET", f"{base_url}/health")
    assert status == 200 and health["status"] == "ok"

    # 使い捨てジョブを作成（存在しない動画パス）。
    status, created = _post_json(f"{base_url}/jobs", {"videoPath": "/nonexistent/e2e-usl99.mp4"})
    assert status == 200
    job_id = created["jobId"]
    project_id = created["projectId"]
    project_dir = projects_dir / project_id

    # 外部エンジンに依存せず終端化するため cancel してから終端待ち。
    _request("POST", f"{base_url}/jobs/{job_id}/cancel")
    _wait_terminal(base_url, job_id)

    # 作成済み: 一覧に出る・ディスクに project ディレクトリがある。
    status, listing = _request("GET", f"{base_url}/jobs")
    assert status == 200
    assert any(item["projectId"] == project_id for item in listing["items"])
    assert project_dir.exists()

    # 削除（実 HTTP）。
    status, body = _request("DELETE", f"{base_url}/jobs/{job_id}")
    assert status == 200
    assert body == {}

    # 一覧から消える・ディスクからも消える。
    status, listing = _request("GET", f"{base_url}/jobs")
    assert status == 200
    assert all(item["projectId"] != project_id for item in listing["items"])
    assert not project_dir.exists()

    # 冪等: 再削除・存在しない ID は 404。
    status, body = _request("DELETE", f"{base_url}/jobs/{job_id}")
    assert status == 404
    assert body["error"]["code"] == "JOB_NOT_FOUND"

    status, body = _request("DELETE", f"{base_url}/jobs/j_does_not_exist")
    assert status == 404
    assert body["error"]["code"] == "JOB_NOT_FOUND"


def test_delete_running_or_queued_returns_409_over_real_http(sidecar) -> None:
    base_url, _ = sidecar

    status, created = _post_json(f"{base_url}/jobs", {"videoPath": "/nonexistent/e2e-usl99-2.mp4"})
    assert status == 200
    job_id = created["jobId"]

    # 作成直後の状態を確認し、queued/running の間は削除が 409 で拒否されること。
    # 終端まで進んでしまっていた場合（外部エンジン不在で即 failed 等）は本ケース対象外。
    _, status_body = _request("GET", f"{base_url}/jobs/{job_id}")
    current: Optional[str] = status_body.get("status")
    code, body = _request("DELETE", f"{base_url}/jobs/{job_id}")
    if current in ("queued", "running"):
        assert code == 409
        assert body["error"]["code"] == "JOB_RUNNING"
    else:
        assert code in (200, 404)
