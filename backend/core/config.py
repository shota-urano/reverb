from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from core.net import validate_loopback_host, validate_loopback_url


@dataclass(frozen=True)
class BackendConfig:
    version: str = "0.6.0"
    host: str = field(default_factory=lambda: os.getenv("REVERB_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("REVERB_PORT", 0))
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv("REVERB_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    )
    voicevox_base_url: str = field(
        default_factory=lambda: os.getenv("REVERB_VOICEVOX_BASE_URL", "http://127.0.0.1:50021")
    )
    dependency_timeout_seconds: float = 0.5
    ffmpeg_bin: str = field(default_factory=lambda: os.getenv("REVERB_FFMPEG_BIN", "ffmpeg"))
    ffprobe_bin: str = field(default_factory=lambda: os.getenv("REVERB_FFPROBE_BIN", "ffprobe"))
    extract_sample_rate: int = field(
        default_factory=lambda: _env_int("REVERB_EXTRACT_SAMPLE_RATE", 16000)
    )
    extract_channels: int = field(default_factory=lambda: _env_int("REVERB_EXTRACT_CHANNELS", 1))
    extract_codec: str = field(
        default_factory=lambda: os.getenv("REVERB_EXTRACT_CODEC", "pcm_s16le")
    )

    # 導入時に最新タグ確認 (verify latest tag at setup time)。
    # モデル名は設定値としてのみ扱い、処理には引数で渡す。
    default_stt_engine: str = field(
        default_factory=lambda: os.getenv("REVERB_STT_ENGINE", "mlx-whisper")
    )
    default_stt_model: str = field(
        default_factory=lambda: os.getenv("REVERB_STT_MODEL", "large-v3")
    )
    default_translate_model: str = field(
        default_factory=lambda: os.getenv("REVERB_TRANSLATE_MODEL", "qwen3:30b")
    )
    default_speaker_id: int = field(default_factory=lambda: _env_int("REVERB_SPEAKER_ID", 13))
    default_speaker_name: str = field(
        default_factory=lambda: os.getenv("REVERB_SPEAKER_NAME", "青山龍星")
    )
    default_style_id: int = field(default_factory=lambda: _env_int("REVERB_STYLE_ID", 0))

    ja_volume: float = 1.0
    original_volume: float = 0.08
    subtitle_target_full_width_chars: int = 20
    subtitle_max_lines: int = 2
    subtitle_min_duration_seconds: float = 1.5

    projects_dir: Path = field(default_factory=lambda: _default_projects_dir())

    def __post_init__(self) -> None:
        # ローカル完結（ルール1）を構造で担保: 待受ホスト・外部エンジンURLは
        # ループバックのみ許可。クラウド/外部ホストが設定されたら起動時に弾く。
        validate_loopback_host("REVERB_HOST", self.host)
        validate_loopback_url("REVERB_OLLAMA_BASE_URL", self.ollama_base_url)
        validate_loopback_url("REVERB_VOICEVOX_BASE_URL", self.voicevox_base_url)
        if self.extract_sample_rate <= 0:
            raise ValueError("REVERB_EXTRACT_SAMPLE_RATE must be greater than 0")
        if self.extract_channels <= 0:
            raise ValueError("REVERB_EXTRACT_CHANNELS must be greater than 0")
        if not self.extract_codec:
            raise ValueError("REVERB_EXTRACT_CODEC must not be empty")

    def with_projects_dir(self, projects_dir: Path) -> "BackendConfig":
        return BackendConfig(
            version=self.version,
            host=self.host,
            port=self.port,
            ollama_base_url=self.ollama_base_url,
            voicevox_base_url=self.voicevox_base_url,
            dependency_timeout_seconds=self.dependency_timeout_seconds,
            ffmpeg_bin=self.ffmpeg_bin,
            ffprobe_bin=self.ffprobe_bin,
            extract_sample_rate=self.extract_sample_rate,
            extract_channels=self.extract_channels,
            extract_codec=self.extract_codec,
            default_stt_engine=self.default_stt_engine,
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


def _env_int(name: str, default: int) -> int:
    """環境変数を安全に int 解釈する。不正値なら既定値を返し起動を止めない。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
