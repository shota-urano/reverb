from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path
from typing import Callable, Mapping, Optional

from core.config import (
    BackendConfig,
    DEFAULT_STT_PROGRESS_INTERVAL_SECONDS,
    DEFAULT_STT_PROGRESS_MAX_FRACTION,
    DEFAULT_STT_PROGRESS_RTF_ESTIMATE,
)
from core.errors import StageError


class WhisperMLXAdapter:
    def __init__(
        self,
        model_repos: Optional[Mapping[str, str]] = None,
        *,
        progress_rtf_estimate: Optional[float] = None,
        progress_max_fraction: Optional[float] = None,
        progress_interval_seconds: Optional[float] = None,
    ) -> None:
        self.model_repos = dict(model_repos or {})
        progress_config = BackendConfig()
        self.progress_rtf_estimate = _positive_float(
            progress_rtf_estimate,
            progress_config.stt_progress_rtf_estimate,
            DEFAULT_STT_PROGRESS_RTF_ESTIMATE,
        )
        self.progress_max_fraction = _fraction_float(
            progress_max_fraction,
            progress_config.stt_progress_max_fraction,
            DEFAULT_STT_PROGRESS_MAX_FRACTION,
        )
        self.progress_interval_seconds = _positive_float(
            progress_interval_seconds,
            progress_config.stt_progress_interval_seconds,
            DEFAULT_STT_PROGRESS_INTERVAL_SECONDS,
        )

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
            reporter = _EstimatedProgressReporter(
                progress_cb=progress_cb,
                duration_seconds=_duration_seconds(options),
                rtf_estimate=self.progress_rtf_estimate,
                max_progress=self.progress_max_fraction,
                interval_seconds=self.progress_interval_seconds,
            )
            reporter.start()
            try:
                raw = mlx_whisper.transcribe(
                    str(audio_path),
                    path_or_hf_repo=resolved_repo,
                    language=language,
                )
            finally:
                reporter.stop()
        except StageError:
            raise
        except Exception as exc:
            raise StageError("STT_FAILED", str(exc)) from exc

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


class _EstimatedProgressReporter:
    def __init__(
        self,
        *,
        progress_cb: Callable[[float], None],
        duration_seconds: float,
        rtf_estimate: float,
        max_progress: float,
        interval_seconds: float,
    ) -> None:
        self.progress_cb = progress_cb
        self.estimated_total_seconds = duration_seconds * rtf_estimate
        self.max_progress = max_progress
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._last_progress = 0.0
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.estimated_total_seconds <= 0:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="whisper-mlx-progress",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        started_at = time.monotonic()
        while not self._stop.wait(self.interval_seconds):
            elapsed = time.monotonic() - started_at
            estimated_fraction = elapsed / self.estimated_total_seconds
            self._report(self.max_progress * estimated_fraction)

    def _report(self, progress: float) -> None:
        clamped = max(0.0, min(progress, self.max_progress))
        if clamped < self._last_progress:
            return
        self._last_progress = clamped
        self.progress_cb(clamped)


def _duration_seconds(options: dict) -> float:
    try:
        return max(0.0, float(options.get("duration") or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _positive_float(
    candidate: Optional[float],
    configured: float,
    fallback: float,
) -> float:
    value = configured if candidate is None else candidate
    if value > 0:
        return value
    return fallback


def _fraction_float(
    candidate: Optional[float],
    configured: float,
    fallback: float,
) -> float:
    value = configured if candidate is None else candidate
    if 0.0 < value < 1.0:
        return value
    return fallback
