from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Optional

import pytest

from adapters.ollama import OllamaAdapter
from core.artifacts import read_glossary, read_translation, write_glossary, write_transcript
from core.config import BackendConfig
from core.job_store import JobStore
from pipeline.stage import PipelineContext
from pipeline.translate import TranslateStage
from schemas.artifacts import Glossary, GlossaryEntry, Transcript, TranscriptSegment
from schemas.settings import default_job_settings


class _GlossaryTranslator:
    def __init__(self, *, glossary_error: Optional[Exception] = None) -> None:
        self.glossary_error = glossary_error
        self.glossary_calls = 0
        self.translate_glossaries: list[list[dict[str, str]]] = []

    def generate_glossary(
        self,
        transcript: str,
        model: str,
        source_lang: Optional[str],
        max_terms: int,
    ) -> list[dict[str, str]]:
        self.glossary_calls += 1
        if self.glossary_error is not None:
            raise self.glossary_error
        assert "harness" in transcript
        assert max_terms == 50
        return [{"source": "harness", "target": "ハーネス"}]

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
        self.translate_glossaries.append(glossary)
        target = "ハーネス" if glossary else "用語集なし"
        return [target for segment in segments if not segment.get("contextOnly")]

    def polish(self, segments, model, system_prompt, temperature):
        return [segment["text"] for segment in segments]


def test_glossary_is_generated_saved_and_injected_into_every_translation_chunk(
    tmp_path: Path,
) -> None:
    translator = _GlossaryTranslator()
    context = _context(
        tmp_path,
        [
            TranscriptSegment(id=0, start=0.0, end=1.0, text="The harness is secure."),
            TranscriptSegment(id=1, start=1.0, end=2.0, text="Inspect the harness."),
        ],
        translate_chunk_size=1,
        translate_chunk_groups=1,
    )

    TranslateStage(translator).run(context)

    glossary = read_glossary(context.project_dir)
    translation = read_translation(context.project_dir)
    expected = [{"source": "harness", "target": "ハーネス"}]
    assert glossary == Glossary(entries=[GlossaryEntry(source="harness", target="ハーネス")])
    assert translator.glossary_calls == 1
    assert translator.translate_glossaries == [expected, expected]
    assert [segment.target for segment in translation.segments] == ["ハーネス", "ハーネス"]


def test_glossary_generation_failure_warns_and_translation_continues_without_glossary(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    translator = _GlossaryTranslator(glossary_error=RuntimeError("glossary failed"))
    context = _context(
        tmp_path,
        [TranscriptSegment(id=0, start=0.0, end=1.0, text="The harness is secure.")],
    )
    caplog.set_level("WARNING", logger="pipeline.translate")

    TranslateStage(translator).run(context)

    assert [segment.target for segment in read_translation(context.project_dir).segments] == [
        "用語集なし"
    ]
    assert translator.translate_glossaries == [[]]
    assert "Glossary generation failed; continuing without glossary." in caplog.text
    assert "RuntimeError: glossary failed" in caplog.text


def test_existing_glossary_is_reused_without_generation(tmp_path: Path) -> None:
    translator = _GlossaryTranslator(glossary_error=AssertionError("must not regenerate"))
    context = _context(
        tmp_path,
        [TranscriptSegment(id=0, start=0.0, end=1.0, text="The harness is secure.")],
    )
    write_glossary(
        context.project_dir,
        Glossary(entries=[GlossaryEntry(source="harness", target="既存訳")]),
    )

    TranslateStage(translator).run(context)

    assert translator.glossary_calls == 0
    assert translator.translate_glossaries == [[{"source": "harness", "target": "既存訳"}]]


def test_disabled_glossary_skips_generation(tmp_path: Path) -> None:
    translator = _GlossaryTranslator(glossary_error=AssertionError("must not generate"))
    context = _context(
        tmp_path,
        [TranscriptSegment(id=0, start=0.0, end=1.0, text="The harness is secure.")],
        translate_glossary_enabled=False,
    )

    TranslateStage(translator).run(context)

    assert translator.glossary_calls == 0
    assert translator.translate_glossaries == [[]]


def test_glossary_config_defaults_env_validation_and_project_dir_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert BackendConfig().translate_glossary_enabled is True
    assert BackendConfig().translate_glossary_max_terms == 50

    monkeypatch.setenv("REVERB_TRANSLATE_GLOSSARY_ENABLED", "false")
    monkeypatch.setenv("REVERB_TRANSLATE_GLOSSARY_MAX_TERMS", "25")
    config = BackendConfig()
    copied = config.with_projects_dir(tmp_path)

    assert config.translate_glossary_enabled is False
    assert config.translate_glossary_max_terms == 25
    assert copied.translate_glossary_enabled is False
    assert copied.translate_glossary_max_terms == 25
    with pytest.raises(ValueError):
        dataclasses.replace(config, translate_glossary_max_terms=0)


def test_ollama_translate_includes_glossary_in_user_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)
    captured_payload: dict = {}

    def post_json(_: str, payload: dict, __: str) -> dict:
        captured_payload.update(payload)
        return {"message": {"content": '[{"id": 0, "text": "ハーネス"}]'}}

    monkeypatch.setattr(adapter, "_post_json", post_json)

    adapter.translate(
        [{"id": 0, "text": "the harness"}],
        "local-model",
        "en",
        "system prompt",
        2,
        [{"source": "harness", "target": "ハーネス"}],
    )

    user_content = json.loads(captured_payload["messages"][1]["content"])
    assert user_content["glossary"] == [{"source": "harness", "target": "ハーネス"}]


def test_ollama_generate_glossary_requests_nouns_and_returns_empty_on_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OllamaAdapter("http://127.0.0.1:11434", timeout_seconds=1)
    captured_payload: dict = {}

    def post_json(_: str, payload: dict, __: str) -> dict:
        captured_payload.update(payload)
        return {"message": {"content": "not json"}}

    monkeypatch.setattr(adapter, "_post_json", post_json)

    result = adapter.generate_glossary("the harness", "local-model", "en", 50)

    assert result == []
    system_prompt = captured_payload["messages"][0]["content"]
    assert "名詞・固有名詞" in system_prompt
    assert "harness AI" in system_prompt
    user_content = json.loads(captured_payload["messages"][1]["content"])
    assert user_content["maxTerms"] == 50
    assert user_content["transcript"] == "the harness"


def _context(
    tmp_path: Path,
    segments: list[TranscriptSegment],
    **config_overrides: object,
) -> PipelineContext:
    config = BackendConfig(
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
            duration=2.0,
            segments=segments,
        ),
    )
    return PipelineContext(config, record, record.project_dir)
