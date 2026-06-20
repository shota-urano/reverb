from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable, Mapping, Optional

from core.errors import StageError


class WhisperMLXAdapter:
    def __init__(self, model_repos: Optional[Mapping[str, str]] = None) -> None:
        self.model_repos = dict(model_repos or {})

    def available(self) -> bool:
        try:
            return importlib.util.find_spec("mlx_whisper") is not None
        except Exception:
            return False

    def transcribe(
        self,
        audio_path: Path,
        model: str,
        language: Optional[str],
        options: dict,
        progress_cb: Callable[[float], None],
    ) -> tuple[Optional[str], list[dict]]:
        progress_cb(0.0)
        try:
            import mlx_whisper
        except ModuleNotFoundError as exc:
            raise StageError("STT_MODEL_MISSING", _model_missing_message(model)) from exc

        try:
            resolved_repo = self._resolve_model(model)
            raw = mlx_whisper.transcribe(
                str(audio_path),
                path_or_hf_repo=resolved_repo,
                language=language,
            )
        except StageError:
            raise
        except Exception as exc:
            raise StageError("STT_FAILED", str(exc)) from exc

        # mlx-whisper does not expose a stable per-segment progress callback here;
        # report coarse start/end progress until the adapter can consume one.
        progress_cb(1.0)
        return raw.get("language") or language, list(raw.get("segments") or [])

    def _resolve_model(self, model: str) -> str:
        # Confirm latest tag at https://huggingface.co/mlx-community at setup time
        configured = self.model_repos.get(model, model)
        local_path = Path(configured).expanduser()
        if local_path.exists():
            return str(local_path)

        try:
            from huggingface_hub import snapshot_download

            return snapshot_download(configured, local_files_only=True)
        except Exception as exc:
            raise StageError("STT_MODEL_MISSING", _model_missing_message(model)) from exc


def _model_missing_message(model: str) -> str:
    return (
        f"STT model is not available locally: {model}. "
        "Install mlx-whisper and pre-cache the configured model before running Reverb. "
        "Do not rely on runtime downloads."
    )
