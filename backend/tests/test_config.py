import dataclasses

import pytest

from core.config import BackendConfig, _env_int
from core.net import is_loopback_host, validate_loopback_url


def test_env_int_falls_back_on_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVERB_TEST_INT", "not-a-number")
    assert _env_int("REVERB_TEST_INT", 42) == 42
    monkeypatch.setenv("REVERB_TEST_INT", "7")
    assert _env_int("REVERB_TEST_INT", 42) == 7


def test_loopback_host_detection() -> None:
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("example.com")
    assert not is_loopback_host("10.0.0.5")


def test_validate_loopback_url_rejects_external_host() -> None:
    assert validate_loopback_url("ollama", "http://127.0.0.1:11434/") == "http://127.0.0.1:11434"
    with pytest.raises(ValueError):
        validate_loopback_url("ollama", "http://evil.example.com:11434")
    with pytest.raises(ValueError):
        validate_loopback_url("ollama", "ftp://127.0.0.1:11434")


def test_backend_config_rejects_non_loopback_engine_url() -> None:
    with pytest.raises(ValueError):
        dataclasses.replace(BackendConfig(), ollama_base_url="http://cloud.example.com:11434")
    with pytest.raises(ValueError):
        dataclasses.replace(BackendConfig(), host="0.0.0.0")


def test_backend_config_rejects_invalid_extract_audio_settings() -> None:
    with pytest.raises(ValueError):
        BackendConfig(extract_sample_rate=0)
    with pytest.raises(ValueError):
        BackendConfig(extract_channels=-1)
    with pytest.raises(ValueError):
        BackendConfig(extract_codec="")


def test_backend_config_uses_current_default_translate_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REVERB_TRANSLATE_MODEL", raising=False)

    assert BackendConfig().default_translate_model == "qwen3:30b-a3b"


def test_backend_config_uses_env_translate_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVERB_TRANSLATE_MODEL", "custom-local-model:latest")

    assert BackendConfig().default_translate_model == "custom-local-model:latest"


def test_backend_config_uses_long_translate_timeout_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REVERB_TRANSLATE_TIMEOUT_SECONDS", raising=False)

    assert BackendConfig().translate_timeout_seconds == 600.0


def test_backend_config_uses_translate_retry_and_keep_alive_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REVERB_TRANSLATE_MAX_RETRIES", "4")
    monkeypatch.setenv("REVERB_TRANSLATE_RETRY_INITIAL_WAIT", "1.5")
    monkeypatch.setenv("REVERB_OLLAMA_KEEP_ALIVE", "2h")

    config = BackendConfig()

    assert config.translate_max_retries == 4
    assert config.translate_retry_initial_wait == 1.5
    assert config.ollama_keep_alive == "2h"


def test_with_projects_dir_preserves_extract_config(tmp_path) -> None:
    config = dataclasses.replace(
        BackendConfig(),
        ffmpeg_bin="custom-ffmpeg",
        ffprobe_bin="custom-ffprobe",
        extract_sample_rate=22050,
        extract_channels=2,
        extract_codec="pcm_f32le",
    )

    copied = config.with_projects_dir(tmp_path)

    assert copied.projects_dir == tmp_path
    assert copied.ffmpeg_bin == "custom-ffmpeg"
    assert copied.ffprobe_bin == "custom-ffprobe"
    assert copied.extract_sample_rate == 22050
    assert copied.extract_channels == 2
    assert copied.extract_codec == "pcm_f32le"
