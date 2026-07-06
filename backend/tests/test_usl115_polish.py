from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Optional

import pytest

from adapters.ollama import OllamaAdapter
from core.artifacts import (
    TRANSLATION_RAW_PATH,
    read_translation,
    read_translation_raw,
    write_transcript,
)
from core.config import BackendConfig, DEFAULT_TRANSLATE_POLISH_SYSTEM_PROMPT
from core.errors import StageError
from core.job_store import JobRecord, JobStore
from pipeline.stub_stages import StubStage
from pipeline.translate import TranslateStage
from schemas.artifacts import Transcript, TranscriptSegment
from schemas.enums import JobState, StageName
from schemas.settings import default_job_settings
from services.pipeline_runner import PipelineRunner


class _PolishTranslator:
    def __init__(
        self,
        *,
        polish_responses: Optional[list[list[str]]] = None,
        polish_error: Optional[Exception] = None,
    ) -> None:
        self.polish_responses = polish_responses or []
        self.polish_error = polish_error
        self.polish_calls: list[dict[str, object]] = []

    def generate_glossary(
        self, transcript: str, model: str, source_lang: Optional[str], max_terms: int
    ) -> list[dict[str, str]]:
        return []

    def warm_up(self, model: str, system_prompt: str) -> None:
        pass

    def translate(
        self,
        segments: list[dict[str, object]],
        model: str,
        source_lang: Optional[str],
        system_prompt: str,
        context_window: int,
        glossary: list[dict[str, str]],
    ) -> list[str]:
        return [f"直訳{segment['id']}" for segment in segments if not segment.get("contextOnly")]

    def polish(
        self,
        segments: list[dict],
        model: str,
        system_prompt: str,
        temperature: float,
    ) -> list[str]:
        self.polish_calls.append(
            {
                "segments": segments,
                "model": model,
                "system_prompt": system_prompt,
                "temperature": temperature,
            }
        )
        if self.polish_error is not None:
            raise self.polish_error
        if self.polish_responses:
            return self.polish_responses.pop(0)
        return [segment["text"] for segment in segments]


def test_polish_enabled_writes_polished_and_raw_translation(tmp_path: Path) -> None:
    translator = _PolishTranslator(polish_responses=[["自然な語りです。"]])

    record = _run_pipeline(tmp_path, translator)

    assert record.status == JobState.done
    assert [segment.target for segment in read_translation(record.project_dir).segments] == [
        "自然な語りです。"
    ]
    assert [segment.target for segment in read_translation_raw(record.project_dir).segments] == [
        "直訳0"
    ]
    assert translator.polish_calls[0]["model"] == record.settings.translate.model


def test_polish_shape_mismatch_falls_back_and_job_succeeds(tmp_path: Path) -> None:
    translator = _PolishTranslator(polish_responses=[[]])

    record = _run_pipeline(tmp_path, translator)

    assert record.status == JobState.done
    assert [segment.target for segment in read_translation(record.project_dir).segments] == [
        "直訳0"
    ]


def test_polish_exception_falls_back_and_job_succeeds(tmp_path: Path) -> None:
    translator = _PolishTranslator(polish_error=RuntimeError("polish failed"))

    record = _run_pipeline(tmp_path, translator)

    assert record.status == JobState.done
    assert [segment.target for segment in read_translation(record.project_dir).segments] == [
        "直訳0"
    ]


def test_polish_disabled_skips_raw_artifact_and_keeps_translation(tmp_path: Path) -> None:
    translator = _PolishTranslator(polish_responses=[["呼ばれてはいけない"]])

    record = _run_pipeline(
        tmp_path,
        translator,
        translate_polish_enabled=False,
    )

    assert record.status == JobState.done
    assert not (record.project_dir / TRANSLATION_RAW_PATH).exists()
    assert [segment.target for segment in read_translation(record.project_dir).segments] == [
        "直訳0"
    ]
    assert translator.polish_calls == []


def test_polish_preserves_segment_ids_and_sends_target_chars(tmp_path: Path) -> None:
    translator = _PolishTranslator(polish_responses=[["推敲7", "推敲11"]])
    segments = [
        TranscriptSegment(id=7, start=0.0, end=2.0, text="First."),
        TranscriptSegment(id=11, start=4.0, end=5.5, text="Second."),
    ]

    record = _run_pipeline(tmp_path, translator, segments=segments)

    translation = read_translation(record.project_dir)
    assert [segment.id for segment in translation.segments] == [7, 11]
    assert [segment.target for segment in translation.segments] == ["推敲7", "推敲11"]
    assert translator.polish_calls[0]["segments"] == [
        {"id": 7, "text": "直訳7", "targetChars": 31},
        {"id": 11, "text": "直訳11", "targetChars": 12},
    ]


def test_empty_polished_text_falls_back_only_that_segment(tmp_path: Path) -> None:
    translator = _PolishTranslator(polish_responses=[["", "自然な二文目です。"]])
    segments = [
        TranscriptSegment(id=0, start=0.0, end=1.0, text="First."),
        TranscriptSegment(id=1, start=3.0, end=4.0, text="Second."),
    ]

    record = _run_pipeline(tmp_path, translator, segments=segments)

    assert [segment.target for segment in read_translation(record.project_dir).segments] == [
        "直訳0",
        "自然な二文目です。",
    ]


def test_polish_config_defaults_env_validation_and_project_dir_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults = BackendConfig()
    assert defaults.translate_polish_enabled is True
    assert defaults.translate_polish_model == ""
    assert defaults.translate_polish_temperature == 0.5
    assert defaults.translate_polish_system_prompt == DEFAULT_TRANSLATE_POLISH_SYSTEM_PROMPT

    monkeypatch.setenv("REVERB_TRANSLATE_POLISH_ENABLED", "false")
    monkeypatch.setenv("REVERB_TRANSLATE_POLISH_MODEL", "local-polisher")
    monkeypatch.setenv("REVERB_TRANSLATE_POLISH_TEMPERATURE", "0.25")
    monkeypatch.setenv("REVERB_TRANSLATE_POLISH_SYSTEM_PROMPT", "custom polish prompt")
    config = BackendConfig()
    copied = config.with_projects_dir(tmp_path)

    assert copied.translate_polish_enabled is False
    assert copied.translate_polish_model == "local-polisher"
    assert copied.translate_polish_temperature == 0.25
    assert copied.translate_polish_system_prompt == "custom polish prompt"
    with pytest.raises(ValueError):
        dataclasses.replace(config, translate_polish_temperature=-0.1)
    with pytest.raises(ValueError):
        dataclasses.replace(config, translate_polish_system_prompt="")


def test_ollama_polish_maps_ids_and_uses_per_call_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OllamaAdapter(
        "http://127.0.0.1:11434",
        timeout_seconds=1,
        temperature=0.9,
    )
    captured_payload: dict = {}

    def post_json(_: str, payload: dict, __: str) -> dict:
        captured_payload.update(payload)
        return {
            "message": {
                "content": json.dumps(
                    [
                        {"id": 9, "text": "九です。"},
                        {"id": 3, "text": "三です。"},
                    ],
                    ensure_ascii=False,
                )
            }
        }

    monkeypatch.setattr(adapter, "_post_json", post_json)
    segments = [
        {"id": 3, "text": "直訳三", "targetChars": 8},
        {"id": 9, "text": "直訳九", "targetChars": 9},
    ]

    result = adapter.polish(segments, "polish-model", "polish prompt", 0.25)

    assert result == ["三です。", "九です。"]
    assert captured_payload["model"] == "polish-model"
    assert captured_payload["options"] == {"temperature": 0.25}
    assert captured_payload["messages"][0] == {
        "role": "system",
        "content": "polish prompt",
    }
    assert json.loads(captured_payload["messages"][1]["content"]) == segments


def test_ollama_polish_rejects_output_without_segment_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)

    def post_json(_: str, payload: dict, __: str) -> dict:
        return {"message": {"content": '[{"text": "推敲文"}]'}}

    monkeypatch.setattr(adapter, "_post_json", post_json)

    with pytest.raises(StageError, match="IDs did not match"):
        adapter.polish(
            [{"id": 4, "text": "直訳文", "targetChars": 8}],
            "polish-model",
            "polish prompt",
            0.5,
        )


def _run_pipeline(
    tmp_path: Path,
    translator: _PolishTranslator,
    *,
    segments: Optional[list[TranscriptSegment]] = None,
    **config_overrides: object,
) -> JobRecord:
    config = BackendConfig(
        translate_glossary_enabled=False,
        translate_chunk_size=10,
        translate_chunk_groups=10,
        translate_retry_initial_wait=0.0,
        **config_overrides,
    ).with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record = store.create("/tmp/input.mp4", default_job_settings(config))
    write_transcript(
        record.project_dir,
        Transcript(
            engine=config.default_stt_engine,
            model=record.settings.stt.model,
            language="en",
            duration=4.0,
            segments=segments or [TranscriptSegment(id=0, start=0.0, end=2.0, text="Original.")],
        ),
    )
    runner = PipelineRunner(
        config,
        store,
        [
            TranslateStage(translator),
            StubStage(StageName.subtitle, "subtitles.json"),
            StubStage(StageName.tts, "tts/seg_0000.wav"),
            StubStage(StageName.mix, "voiceover.wav"),
        ],
        lambda job: None,
    )

    runner.run(record)
    return record
