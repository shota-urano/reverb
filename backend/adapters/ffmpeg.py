from __future__ import annotations

import shutil


class FFmpegAdapter:
    def available(self) -> bool:
        return shutil.which("ffmpeg") is not None
