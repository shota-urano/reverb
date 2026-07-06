from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from core.artifacts import write_transcript
from core.config import BackendConfig
from core.job_store import JobStore
from pipeline.stage import PipelineContext
from pipeline.translate import TranslateStage
from schemas.artifacts import Transcript, TranscriptSegment
from schemas.settings import default_job_settings
from test_usl115_polish import _PolishTranslator


def test_polish_enabled_reports_monotonic_progress_through_polish(
    tmp_path: Path,
) -> None:
    progress_values, translator = _run_translate_stage(tmp_path, polish_enabled=True)

    assert all(
        current >= previous for previous, current in zip(progress_values, progress_values[1:])
    )
    assert progress_values == pytest.approx([0.0, 0.3, 0.6, 0.9, 0.925, 0.95, 0.975, 1.0])
    assert len(translator.polish_calls) == 3


def test_polish_disabled_reaches_one_during_translation_without_polish_reports(
    tmp_path: Path,
) -> None:
    progress_values, translator = _run_translate_stage(tmp_path, polish_enabled=False)

    assert progress_values == pytest.approx([0.0, 1 / 3, 2 / 3, 1.0])
    assert translator.polish_calls == []


def test_polish_progress_share_config_defaults_env_validation_and_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert BackendConfig().translate_polish_progress_share == 0.1

    monkeypatch.setenv("REVERB_TRANSLATE_POLISH_PROGRESS_SHARE", "0.2")
    config = BackendConfig()

    assert config.translate_polish_progress_share == 0.2
    assert config.with_projects_dir(tmp_path).translate_polish_progress_share == 0.2
    with pytest.raises(ValueError):
        dataclasses.replace(config, translate_polish_progress_share=0.0)
    with pytest.raises(ValueError):
        dataclasses.replace(config, translate_polish_progress_share=1.0)


def _run_translate_stage(
    tmp_path: Path,
    *,
    polish_enabled: bool,
) -> tuple[list[float], _PolishTranslator]:
    progress_values: list[float] = []
    config = BackendConfig(
        translate_glossary_enabled=False,
        translate_dedup_enabled=False,
        translate_chunk_size=1,
        translate_chunk_groups=1,
        translate_polish_enabled=polish_enabled,
        translate_polish_context_window=0,
        translate_progress_estimated_chunk_seconds=3600.0,
        translate_progress_interval_seconds=3600.0,
    ).with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    job = store.create(str(tmp_path / "input.mp4"), default_job_settings(config))
    write_transcript(
        job.project_dir,
        Transcript(
            engine=config.default_stt_engine,
            model=job.settings.stt.model,
            language="en",
            duration=7.0,
            segments=[
                TranscriptSegment(id=0, start=0.0, end=1.0, text="First."),
                TranscriptSegment(id=1, start=3.0, end=4.0, text="Second."),
                TranscriptSegment(id=2, start=6.0, end=7.0, text="Third."),
            ],
        ),
    )
    context = PipelineContext(
        config=config,
        job=job,
        project_dir=job.project_dir,
        report_progress=progress_values.append,
    )
    translator = _PolishTranslator()

    TranslateStage(translator).run(context)

    return progress_values, translator
