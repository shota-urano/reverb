from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class BackendConfig:
    version: str = "0.6.0"
    host: str = field(default_factory=lambda: os.getenv("REVERB_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("REVERB_PORT", "0")))
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv("REVERB_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    )
    voicevox_base_url: str = field(
        default_factory=lambda: os.getenv("REVERB_VOICEVOX_BASE_URL", "http://127.0.0.1:50021")
    )
    dependency_timeout_seconds: float = 0.5

    # 導入時に最新タグ確認。モデル名は設定値としてのみ扱い、処理には引数で渡す。
    default_stt_model: str = field(
        default_factory=lambda: os.getenv("REVERB_STT_MODEL", "large-v3")
    )
    default_translate_model: str = field(
        default_factory=lambda: os.getenv("REVERB_TRANSLATE_MODEL", "qwen3:30b")
    )
    default_speaker_id: int = field(
        default_factory=lambda: int(os.getenv("REVERB_SPEAKER_ID", "13"))
    )
    default_speaker_name: str = field(
        default_factory=lambda: os.getenv("REVERB_SPEAKER_NAME", "青山龍星")
    )
    default_style_id: int = field(default_factory=lambda: int(os.getenv("REVERB_STYLE_ID", "0")))

    ja_volume: float = 1.0
    original_volume: float = 0.08
    subtitle_target_full_width_chars: int = 20
    subtitle_max_lines: int = 2
    subtitle_min_duration_seconds: float = 1.5

    projects_dir: Path = field(default_factory=lambda: _default_projects_dir())

    def with_projects_dir(self, projects_dir: Path) -> "BackendConfig":
        return BackendConfig(
            version=self.version,
            host=self.host,
            port=self.port,
            ollama_base_url=self.ollama_base_url,
            voicevox_base_url=self.voicevox_base_url,
            dependency_timeout_seconds=self.dependency_timeout_seconds,
            default_stt_model=self.default_stt_model,
            default_translate_model=self.default_translate_model,
            default_speaker_id=self.default_speaker_id,
            default_speaker_name=self.default_speaker_name,
            default_style_id=self.default_style_id,
            ja_volume=self.ja_volume,
            original_volume=self.original_volume,
            subtitle_target_full_width_chars=self.subtitle_target_full_width_chars,
            subtitle_max_lines=self.subtitle_max_lines,
            subtitle_min_duration_seconds=self.subtitle_min_duration_seconds,
            projects_dir=projects_dir,
        )


def _default_projects_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "Reverb" / "projects"
