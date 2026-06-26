from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from core.net import validate_loopback_host, validate_loopback_url


DEFAULT_STT_PROGRESS_RTF_ESTIMATE = 0.5
DEFAULT_STT_PROGRESS_MAX_FRACTION = 0.95
DEFAULT_STT_PROGRESS_INTERVAL_SECONDS = 0.25
DEFAULT_TRANSLATE_PROGRESS_ESTIMATED_CHUNK_SECONDS = 30.0
DEFAULT_TRANSLATE_PROGRESS_INTERVAL_SECONDS = 0.25
DEFAULT_TTS_PROGRESS_ESTIMATED_CUE_SECONDS = 2.0
DEFAULT_TTS_PROGRESS_INTERVAL_SECONDS = 0.25
DEFAULT_MIX_PROGRESS_ESTIMATED_ITEM_SECONDS = 5.0
DEFAULT_MIX_PROGRESS_INTERVAL_SECONDS = 0.25


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
    default_tts_engine: str = field(
        default_factory=lambda: os.getenv("REVERB_TTS_ENGINE", "aivisspeech")
    )
    aivisspeech_base_url: str = field(
        default_factory=lambda: os.getenv(
            "REVERB_AIVISSPEECH_BASE_URL",
            "http://127.0.0.1:10101",
        )
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
    thumbnail_offset_seconds: float = field(
        default_factory=lambda: _env_float("REVERB_THUMBNAIL_OFFSET_SECONDS", 1.0)
    )
    thumbnail_width: int = field(default_factory=lambda: _env_int("REVERB_THUMBNAIL_WIDTH", 320))

    # 導入時に最新タグ確認 (verify latest tag at setup time)。
    # モデル名は設定値としてのみ扱い、処理には引数で渡す。
    default_stt_engine: str = field(
        default_factory=lambda: os.getenv("REVERB_STT_ENGINE", "mlx-whisper")
    )
    default_stt_model: str = field(
        default_factory=lambda: os.getenv("REVERB_STT_MODEL", "large-v3")
    )
    # 論理STTモデル名 → mlx-whisper の HF リポジトリ解決表。タグはここ（設定値）に集約。
    # 導入時に最新タグ確認: https://huggingface.co/mlx-community
    # REVERB_STT_MODEL_REPOS="large-v3=mlx-community/whisper-large-v3-mlx,..." で上書き可。
    stt_model_repos: Dict[str, str] = field(default_factory=lambda: _stt_model_repos())
    # Adjust after real-world measurement on Apple Silicon.
    stt_progress_rtf_estimate: float = field(
        default_factory=lambda: _env_float(
            "REVERB_STT_PROGRESS_RTF_ESTIMATE",
            DEFAULT_STT_PROGRESS_RTF_ESTIMATE,
        )
    )
    stt_progress_max_fraction: float = field(
        default_factory=lambda: _env_float(
            "REVERB_STT_PROGRESS_MAX_FRACTION",
            DEFAULT_STT_PROGRESS_MAX_FRACTION,
        )
    )
    stt_progress_interval_seconds: float = field(
        default_factory=lambda: _env_float(
            "REVERB_STT_PROGRESS_INTERVAL_SECONDS",
            DEFAULT_STT_PROGRESS_INTERVAL_SECONDS,
        )
    )
    # TODO: adjust after real-world profiling
    translate_progress_estimated_chunk_seconds: float = field(
        default_factory=lambda: _env_float(
            "REVERB_TRANSLATE_PROGRESS_ESTIMATED_CHUNK_SECONDS",
            DEFAULT_TRANSLATE_PROGRESS_ESTIMATED_CHUNK_SECONDS,
        )
    )
    # TODO: adjust after real-world profiling
    translate_progress_interval_seconds: float = field(
        default_factory=lambda: _env_float(
            "REVERB_TRANSLATE_PROGRESS_INTERVAL_SECONDS",
            DEFAULT_TRANSLATE_PROGRESS_INTERVAL_SECONDS,
        )
    )
    # TODO: adjust after real-world profiling
    tts_progress_estimated_cue_seconds: float = field(
        default_factory=lambda: _env_float(
            "REVERB_TTS_PROGRESS_ESTIMATED_CUE_SECONDS",
            DEFAULT_TTS_PROGRESS_ESTIMATED_CUE_SECONDS,
        )
    )
    # TODO: adjust after real-world profiling
    tts_progress_interval_seconds: float = field(
        default_factory=lambda: _env_float(
            "REVERB_TTS_PROGRESS_INTERVAL_SECONDS",
            DEFAULT_TTS_PROGRESS_INTERVAL_SECONDS,
        )
    )
    # TODO: adjust after real-world profiling
    mix_progress_estimated_item_seconds: float = field(
        default_factory=lambda: _env_float(
            "REVERB_MIX_PROGRESS_ESTIMATED_ITEM_SECONDS",
            DEFAULT_MIX_PROGRESS_ESTIMATED_ITEM_SECONDS,
        )
    )
    # TODO: adjust after real-world profiling
    mix_progress_interval_seconds: float = field(
        default_factory=lambda: _env_float(
            "REVERB_MIX_PROGRESS_INTERVAL_SECONDS",
            DEFAULT_MIX_PROGRESS_INTERVAL_SECONDS,
        )
    )
    # NOTE: confirm latest model tag at install time. モデル名は設定値としてのみ扱う。
    default_translate_model: str = field(
        default_factory=lambda: os.getenv("REVERB_TRANSLATE_MODEL", "qwen3:30b-a3b")
    )
    # qwen3:30b-a3b は実測で約53秒/8セグメント。コールドロード込みの
    # 初回チャンクは300〜600秒程度を見込むため、既定を長尺動画向けにする。
    translate_timeout_seconds: float = field(
        default_factory=lambda: _env_float("REVERB_TRANSLATE_TIMEOUT_SECONDS", 600.0)
    )
    ollama_keep_alive: str = field(
        default_factory=lambda: os.getenv("REVERB_OLLAMA_KEEP_ALIVE", "3600s")
    )
    translate_max_retries: int = field(
        default_factory=lambda: _env_int("REVERB_TRANSLATE_MAX_RETRIES", 3)
    )
    translate_retry_initial_wait: float = field(
        default_factory=lambda: _env_float("REVERB_TRANSLATE_RETRY_INITIAL_WAIT", 5.0)
    )
    translate_fallback_threshold: float = field(
        default_factory=lambda: _env_float("REVERB_TRANSLATE_FALLBACK_THRESHOLD", 0.5)
    )
    translate_chunk_size: int = field(
        default_factory=lambda: _env_int("REVERB_TRANSLATE_CHUNK_SIZE", 10)
    )
    translate_context_window: int = field(
        default_factory=lambda: _env_int("REVERB_TRANSLATE_CONTEXT_WINDOW", 2)
    )
    # 翻訳生成の温度。低すぎると直訳寄り・高すぎると不安定になるため、
    # 自然さと一貫性のバランスで既定 0.7。設定値として切替可能に保つ。
    translate_temperature: float = field(
        default_factory=lambda: _env_float("REVERB_TRANSLATE_TEMPERATURE", 0.7)
    )
    translate_system_prompt: str = field(
        default_factory=lambda: os.getenv(
            "REVERB_TRANSLATE_SYSTEM_PROMPT",
            (
                "あなたは外国語ナレーション動画を日本語字幕に翻訳するプロの翻訳者です。"
                "inputSegments の各文を、原文の意味を保ったまま自然で分かりやすい日本語に翻訳してください。\n"
                "# 翻訳方針\n"
                "- 逐語訳・直訳をしない。英語の語順や言い回しをそのまま日本語に置き換えず、"
                "日本語として自然な表現に意訳する。\n"
                "- 文体は落ち着いた「です・ます」調のナレーション。視聴者がすっと理解できる平易な言葉を選ぶ。\n"
                "- 不自然なカタカナ語の多用や翻訳調の硬い言い回しを避け、一般的な日本語表現に言い換える。\n"
                "- 同一の固有名詞や専門用語は訳文全体で表記を統一する。\n"
                "- contextSegments は前後の文脈を理解するための参考情報であり、翻訳・出力はしない。"
                "代名詞や省略はこの文脈を踏まえて自然に補う。\n"
                "- 字幕用に簡潔にする。ただし意味・情報を削らず、勝手な追加もしない。\n"
                "# 出力形式\n"
                "inputSegments と同じ id を持つ JSONオブジェクト配列のみを返す。"
                '各要素は {"id": <入力と同じid>, "text": "<日本語訳>"} の形式。'
                "text に記号装飾や改行を入れない。説明・コードフェンス・余分な文字は一切出力しない。"
            ),
        )
    )
    # 導入時に話者ID確認。既定エンジン AivisSpeech の「阿井田 茂 / ノーマル」
    # （落ち着いた男性ナレーション, ACML 1.0, USL-92 採用）を既定値にする。
    # VOICEVOX に切替える場合は REVERB_SPEAKER_ID/STYLE_ID を VOICEVOX 側の
    # 話者ID（例: 青山龍星 ノーマル=13）で上書きする。/speakers で確認可。
    # 合成は style_id を VOICEVOX 互換 API の speaker パラメータに渡す。
    default_speaker_id: int = field(
        default_factory=lambda: _env_int("REVERB_SPEAKER_ID", 1310138976)
    )
    default_speaker_name: str = field(
        default_factory=lambda: os.getenv("REVERB_SPEAKER_NAME", "阿井田 茂")
    )
    default_style_id: int = field(default_factory=lambda: _env_int("REVERB_STYLE_ID", 1310138976))
    # VOICEVOX 互換TTSエンジン共通の合成タイムアウト。既存環境変数との互換を
    # 優先し、AivisSpeech でも同じ値を使う。
    voicevox_synthesis_timeout_seconds: float = field(
        default_factory=lambda: _env_float("REVERB_VOICEVOX_SYNTHESIS_TIMEOUT_SECONDS", 30.0)
    )
    tts_cue_retry_count: int = field(
        default_factory=lambda: _env_int("REVERB_TTS_CUE_RETRY_COUNT", 2)
    )

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
        validate_loopback_url("REVERB_AIVISSPEECH_BASE_URL", self.aivisspeech_base_url)
        if self.default_tts_engine not in {"aivisspeech", "voicevox"}:
            raise ValueError("REVERB_TTS_ENGINE must be one of: aivisspeech, voicevox")
        if self.extract_sample_rate <= 0:
            raise ValueError("REVERB_EXTRACT_SAMPLE_RATE must be greater than 0")
        if self.extract_channels <= 0:
            raise ValueError("REVERB_EXTRACT_CHANNELS must be greater than 0")
        if not self.extract_codec:
            raise ValueError("REVERB_EXTRACT_CODEC must not be empty")
        if self.thumbnail_offset_seconds < 0:
            raise ValueError("REVERB_THUMBNAIL_OFFSET_SECONDS must be greater than or equal to 0")
        if self.thumbnail_width <= 0:
            raise ValueError("REVERB_THUMBNAIL_WIDTH must be greater than 0")
        if self.translate_timeout_seconds <= 0:
            raise ValueError("REVERB_TRANSLATE_TIMEOUT_SECONDS must be greater than 0")
        if self.stt_progress_rtf_estimate <= 0:
            raise ValueError("REVERB_STT_PROGRESS_RTF_ESTIMATE must be greater than 0")
        if self.stt_progress_max_fraction <= 0 or self.stt_progress_max_fraction >= 1:
            raise ValueError("REVERB_STT_PROGRESS_MAX_FRACTION must be in the range (0.0, 1.0)")
        if self.stt_progress_interval_seconds <= 0:
            raise ValueError("REVERB_STT_PROGRESS_INTERVAL_SECONDS must be greater than 0")
        if self.translate_progress_estimated_chunk_seconds <= 0:
            raise ValueError(
                "REVERB_TRANSLATE_PROGRESS_ESTIMATED_CHUNK_SECONDS must be greater than 0"
            )
        if self.translate_progress_interval_seconds <= 0:
            raise ValueError("REVERB_TRANSLATE_PROGRESS_INTERVAL_SECONDS must be greater than 0")
        if self.tts_progress_estimated_cue_seconds <= 0:
            raise ValueError("REVERB_TTS_PROGRESS_ESTIMATED_CUE_SECONDS must be greater than 0")
        if self.tts_progress_interval_seconds <= 0:
            raise ValueError("REVERB_TTS_PROGRESS_INTERVAL_SECONDS must be greater than 0")
        if self.mix_progress_estimated_item_seconds <= 0:
            raise ValueError("REVERB_MIX_PROGRESS_ESTIMATED_ITEM_SECONDS must be greater than 0")
        if self.mix_progress_interval_seconds <= 0:
            raise ValueError("REVERB_MIX_PROGRESS_INTERVAL_SECONDS must be greater than 0")
        if not self.ollama_keep_alive:
            raise ValueError("REVERB_OLLAMA_KEEP_ALIVE must not be empty")
        if self.translate_max_retries < 0:
            raise ValueError("REVERB_TRANSLATE_MAX_RETRIES must be greater than or equal to 0")
        if self.translate_retry_initial_wait < 0:
            raise ValueError(
                "REVERB_TRANSLATE_RETRY_INITIAL_WAIT must be greater than or equal to 0"
            )
        if self.translate_fallback_threshold <= 0 or self.translate_fallback_threshold > 1:
            raise ValueError("REVERB_TRANSLATE_FALLBACK_THRESHOLD must be in the range (0.0, 1.0]")
        if self.translate_chunk_size <= 0:
            raise ValueError("REVERB_TRANSLATE_CHUNK_SIZE must be greater than 0")
        if self.translate_context_window < 0:
            raise ValueError("REVERB_TRANSLATE_CONTEXT_WINDOW must be greater than or equal to 0")
        if self.translate_temperature < 0:
            raise ValueError("REVERB_TRANSLATE_TEMPERATURE must be greater than or equal to 0")
        if not self.translate_system_prompt:
            raise ValueError("REVERB_TRANSLATE_SYSTEM_PROMPT must not be empty")
        if self.voicevox_synthesis_timeout_seconds <= 0:
            raise ValueError("REVERB_VOICEVOX_SYNTHESIS_TIMEOUT_SECONDS must be greater than 0")
        if self.tts_cue_retry_count < 0:
            raise ValueError("REVERB_TTS_CUE_RETRY_COUNT must be greater than or equal to 0")

    def with_projects_dir(self, projects_dir: Path) -> "BackendConfig":
        return BackendConfig(
            version=self.version,
            host=self.host,
            port=self.port,
            ollama_base_url=self.ollama_base_url,
            voicevox_base_url=self.voicevox_base_url,
            default_tts_engine=self.default_tts_engine,
            aivisspeech_base_url=self.aivisspeech_base_url,
            dependency_timeout_seconds=self.dependency_timeout_seconds,
            ffmpeg_bin=self.ffmpeg_bin,
            ffprobe_bin=self.ffprobe_bin,
            extract_sample_rate=self.extract_sample_rate,
            extract_channels=self.extract_channels,
            extract_codec=self.extract_codec,
            thumbnail_offset_seconds=self.thumbnail_offset_seconds,
            thumbnail_width=self.thumbnail_width,
            default_stt_engine=self.default_stt_engine,
            default_stt_model=self.default_stt_model,
            stt_model_repos=self.stt_model_repos,
            stt_progress_rtf_estimate=self.stt_progress_rtf_estimate,
            stt_progress_max_fraction=self.stt_progress_max_fraction,
            stt_progress_interval_seconds=self.stt_progress_interval_seconds,
            translate_progress_estimated_chunk_seconds=(
                self.translate_progress_estimated_chunk_seconds
            ),
            translate_progress_interval_seconds=self.translate_progress_interval_seconds,
            tts_progress_estimated_cue_seconds=self.tts_progress_estimated_cue_seconds,
            tts_progress_interval_seconds=self.tts_progress_interval_seconds,
            mix_progress_estimated_item_seconds=self.mix_progress_estimated_item_seconds,
            mix_progress_interval_seconds=self.mix_progress_interval_seconds,
            default_translate_model=self.default_translate_model,
            translate_timeout_seconds=self.translate_timeout_seconds,
            ollama_keep_alive=self.ollama_keep_alive,
            translate_max_retries=self.translate_max_retries,
            translate_retry_initial_wait=self.translate_retry_initial_wait,
            translate_fallback_threshold=self.translate_fallback_threshold,
            translate_chunk_size=self.translate_chunk_size,
            translate_context_window=self.translate_context_window,
            translate_temperature=self.translate_temperature,
            translate_system_prompt=self.translate_system_prompt,
            default_speaker_id=self.default_speaker_id,
            default_speaker_name=self.default_speaker_name,
            default_style_id=self.default_style_id,
            voicevox_synthesis_timeout_seconds=self.voicevox_synthesis_timeout_seconds,
            tts_cue_retry_count=self.tts_cue_retry_count,
            ja_volume=self.ja_volume,
            original_volume=self.original_volume,
            subtitle_target_full_width_chars=self.subtitle_target_full_width_chars,
            subtitle_max_lines=self.subtitle_max_lines,
            subtitle_min_duration_seconds=self.subtitle_min_duration_seconds,
            projects_dir=projects_dir,
        )


def _stt_model_repos() -> Dict[str, str]:
    """論理STTモデル名→HFリポジトリの解決表。既定値はここに集約し、ハードコード散在を防ぐ。
    導入時に最新タグ確認: https://huggingface.co/mlx-community 。環境変数で上書き可。"""
    defaults = {
        "large-v3": "mlx-community/whisper-large-v3-mlx",
        "turbo": "mlx-community/whisper-large-v3-turbo",
    }
    raw = os.getenv("REVERB_STT_MODEL_REPOS")
    if not raw:
        return defaults
    overrides: Dict[str, str] = {}
    for pair in raw.split(","):
        name, sep, repo = pair.partition("=")
        name, repo = name.strip(), repo.strip()
        if sep and name and repo:
            overrides[name] = repo
    return {**defaults, **overrides}


def _default_projects_dir() -> Path:
    # 保存先はコードに固定せず設定値に切り出す（ルール6）。テスト/別環境では
    # REVERB_PROJECTS_DIR で一時ディレクトリ等に差し替えられるようにする。
    override = os.getenv("REVERB_PROJECTS_DIR")
    if override:
        return Path(override).expanduser()
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


def _env_float(name: str, default: float) -> float:
    """環境変数を安全に float 解釈する。不正値なら既定値を返し起動を止めない。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
