from __future__ import annotations

import importlib.util


class WhisperMLXAdapter:
    def available(self) -> bool:
        try:
            return importlib.util.find_spec("mlx_whisper") is not None
        except Exception:
            return False
