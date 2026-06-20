from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict

from core.errors import StageError


def _parse_progress_time(raw: str) -> float:
    hours, minutes, seconds = raw.split(":", 2)
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


class FFmpegAdapter:
    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe") -> None:
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin

    def available(self) -> bool:
        return (
            shutil.which(self.ffmpeg_bin) is not None and shutil.which(self.ffprobe_bin) is not None
        )

    def probe(self, video_path: str) -> tuple[bool, float]:
        if shutil.which(self.ffprobe_bin) is None:
            raise StageError(
                code="FFMPEG_UNAVAILABLE",
                message=f"ffprobe binary not found: {self.ffprobe_bin}",
            )

        result = subprocess.run(
            [
                self.ffprobe_bin,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                video_path,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise StageError(code="EXTRACT_FAILED", message=result.stderr.strip())

        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise StageError(code="EXTRACT_FAILED", message=str(exc)) from exc
        streams = payload.get("streams", [])
        has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
        duration = float(payload.get("format", {}).get("duration") or 0.0)
        return has_audio, duration

    def extract(
        self,
        video_path: str,
        out_path: Path,
        options: Dict[str, object],
        progress_cb: Callable[[float], None],
    ) -> None:
        if shutil.which(self.ffmpeg_bin) is None:
            raise StageError(
                code="FFMPEG_UNAVAILABLE",
                message=f"ffmpeg binary not found: {self.ffmpeg_bin}",
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_name(f"{out_path.name}.tmp")
        duration = float(options.get("duration") or 0.0)
        command = [
            self.ffmpeg_bin,
            "-i",
            video_path,
            "-vn",
            "-ac",
            str(options["channels"]),
            "-ar",
            str(options["sample_rate"]),
            "-c:a",
            str(options["codec"]),
            "-progress",
            "pipe:1",
            "-y",
            str(tmp_path),
        ]

        progress_cb(0.0)
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_file:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                text=True,
            )
            assert process.stdout is not None
            for line in process.stdout:
                key, _, value = line.strip().partition("=")
                if key == "out_time" and duration > 0:
                    progress_cb(max(0.0, min(_parse_progress_time(value) / duration, 1.0)))
            return_code = process.wait()
            stderr_file.seek(0)
            stderr = stderr_file.read().strip()

        if return_code != 0:
            if tmp_path.exists():
                tmp_path.unlink()
            raise StageError(code="EXTRACT_FAILED", message=stderr)

        os.replace(tmp_path, out_path)
        progress_cb(1.0)
