from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from core.artifacts import read_translation, write_transcript
from core.config import BackendConfig
from core.errors import StageError
from pipeline.stage import PipelineContext
from pipeline.translate import TranslateStage, _needs_translation
from schemas.artifacts import Transcript, TranscriptSegment
from schemas.settings import default_job_settings


class FakeTranslator:
    def __init__(self, responses: list[list[str]]) -> None:
        self.responses = responses
        self.calls: list[list[dict[str, object]]] = []

    def warm_up(self, model: str, system_prompt: str) -> None:
        pass

    def translate(
        self,
        segments: list[dict[str, object]],
        model: str,
        source_lang: Optional[str],
        system_prompt: str,
        context_window: int,
    ) -> list[str]:
        self.calls.append(segments)
        return self.responses.pop(0)


@pytest.mark.parametrize("text", ["", "  ", ".", "...", "!?", "---"])
def test_needs_translation_returns_false_for_symbol_only_text(text: str) -> None:
    assert _needs_translation(text) is False


@pytest.mark.parametrize("text", ["Hello", "123", "日本語", ". Hello"])
def test_needs_translation_returns_true_for_word_text(text: str) -> None:
    assert _needs_translation(text) is True


def test_translate_passthrough_symbol_only_segment_without_stage_failure(
    tmp_path: Path,
) -> None:
    translator = FakeTranslator(responses=[["こんにちは"]])

    TranslateStage(translator).run(
        _context(
            tmp_path,
            [
                TranscriptSegment(id=1, start=0.0, end=1.0, text="Hello world"),
                TranscriptSegment(id=2, start=1.0, end=2.0, text="."),
            ],
        )
    )

    translation = read_translation(tmp_path)
    assert [segment.target for segment in translation.segments] == ["こんにちは", "."]
    assert translator.calls == [
        [
            {
                "id": 1,
                "start": 0.0,
                "end": 1.0,
                "text": "Hello world",
                "contextOnly": False,
            }
        ]
    ]


def test_translate_incomplete_still_fails_for_translatable_empty_target(
    tmp_path: Path,
) -> None:
    translator = FakeTranslator(responses=[[""], [""]])

    with pytest.raises(StageError) as exc_info:
        TranslateStage(translator).run(
            _context(
                tmp_path,
                [
                    TranscriptSegment(id=1, start=0.0, end=1.0, text="Real sentence here"),
                ],
            )
        )

    assert exc_info.value.code == "TRANSLATE_INCOMPLETE"
    assert len(translator.calls) == 2


def _context(tmp_path: Path, segments: list[TranscriptSegment]) -> PipelineContext:
    config = BackendConfig(
        translate_max_retries=1,
        translate_retry_initial_wait=0.0,
    )
    write_transcript(
        tmp_path,
        Transcript(
            engine=config.default_stt_engine,
            model=config.default_stt_model,
            language="en",
            duration=2.0,
            segments=segments,
        ),
    )
    return PipelineContext(
        config=config,
        job=SimpleNamespace(settings=default_job_settings(config)),
        project_dir=tmp_path,
    )
