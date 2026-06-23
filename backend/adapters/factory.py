from __future__ import annotations

from adapters.voicevox_compatible import AivisSpeechAdapter, VoicevoxAdapter
from core.config import BackendConfig
from pipeline.tts import TtsSynthesizer


def build_tts_adapter(config: BackendConfig) -> TtsSynthesizer:
    if config.default_tts_engine == "aivisspeech":
        return AivisSpeechAdapter(
            config.aivisspeech_base_url,
            config.dependency_timeout_seconds,
            config.voicevox_synthesis_timeout_seconds,
        )
    if config.default_tts_engine == "voicevox":
        return VoicevoxAdapter(
            config.voicevox_base_url,
            config.dependency_timeout_seconds,
            config.voicevox_synthesis_timeout_seconds,
        )
    raise ValueError(f"Unsupported TTS engine: {config.default_tts_engine}")
