from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.artifacts import read_subtitles, write_translation
from core.config import BackendConfig
from core.job_store import JobRecord, JobStore
from pipeline.stub_stages import StubStage
from pipeline.subtitle import SubtitleStage
from schemas.artifacts import Translation, TranslationSegment
from schemas.enums import JobState, StageName, StageState
from schemas.settings import default_job_settings
from services.pipeline_runner import PipelineRunner


def test_subtitle_long_text_splits_into_multiple_non_overlapping_cues(tmp_path: Path) -> None:
    record, _ = _run_pipeline(
        tmp_path,
        segments=[
            TranslationSegment(
                id=3,
                start=0.0,
                end=9.0,
                source="Long source.",
                target=(
                    "今日は字幕整形の仕組みについて説明します。"
                    "まず翻訳済みの長い文章を意味の切れ目で分割し、"
                    "次に読みやすい行に整えます。"
                ),
            )
        ],
    )

    subtitles = read_subtitles(record.project_dir)
    assert record.status == JobState.done
    assert record.stages[StageName.subtitle].status == StageState.done
    assert len(subtitles.cues) > 1
    assert [cue.id for cue in subtitles.cues] == list(range(len(subtitles.cues)))
    assert all(cue.segmentIds == [3] for cue in subtitles.cues)
    assert _has_no_overlaps(subtitles.cues)


def test_subtitle_short_text_extends_to_minimum_duration_when_gap_allows(tmp_path: Path) -> None:
    record, _ = _run_pipeline(
        tmp_path,
        segments=[
            TranslationSegment(
                id=0,
                start=0.0,
                end=0.5,
                source="Hi.",
                target="こんにちは。",
            ),
            TranslationSegment(
                id=1,
                start=3.0,
                end=4.0,
                source="Next.",
                target="次です。",
            ),
        ],
    )

    first = read_subtitles(record.project_dir).cues[0]
    assert first.start == 0.0
    assert first.end == 1.5
    assert first.segmentIds == [0]


def test_subtitle_short_adjacent_text_merges_when_extension_would_overlap(tmp_path: Path) -> None:
    record, _ = _run_pipeline(
        tmp_path,
        segments=[
            TranslationSegment(
                id=0,
                start=0.0,
                end=0.4,
                source="Hi.",
                target="短い。",
            ),
            TranslationSegment(
                id=1,
                start=0.4,
                end=1.8,
                source="Again.",
                target="続きです。",
            ),
        ],
    )

    subtitles = read_subtitles(record.project_dir)
    assert len(subtitles.cues) == 1
    assert subtitles.cues[0].end - subtitles.cues[0].start >= 1.5
    assert subtitles.cues[0].segmentIds == [0, 1]


def test_subtitle_empty_translation_writes_empty_cues_with_done_status(tmp_path: Path) -> None:
    record, notifications = _run_pipeline(
        tmp_path,
        segments=[
            TranslationSegment(id=0, start=0.0, end=1.0, source=" ", target=" "),
            TranslationSegment(id=1, start=1.0, end=2.0, source="", target=""),
        ],
    )

    subtitles = read_subtitles(record.project_dir)
    assert record.status == JobState.done
    assert record.stages[StageName.subtitle].status == StageState.done
    assert record.stages[StageName.subtitle].artifact == "subtitles.json"
    assert subtitles.cues == []
    subtitle_progress = [
        snapshot.stages[3].progress
        for snapshot in notifications
        if snapshot.currentStage == "subtitle"
    ]
    assert subtitle_progress[0] == 0.0
    assert subtitle_progress[-1] == 1.0


def test_subtitle_lines_stay_within_configured_shape_and_keep_segment_ids(
    tmp_path: Path,
) -> None:
    record, _ = _run_pipeline(
        tmp_path,
        segments=[
            TranslationSegment(
                id=7,
                start=1.0,
                end=6.0,
                source="Source.",
                target="本日は字幕整形について説明し、読みやすい表示に整えます。",
            )
        ],
    )

    config = BackendConfig().with_projects_dir(tmp_path)
    subtitles = read_subtitles(record.project_dir)
    assert subtitles.cues
    for cue in subtitles.cues:
        assert len(cue.lines) <= config.subtitle_max_lines
        assert all(len(line) <= config.subtitle_target_full_width_chars for line in cue.lines)
        assert cue.segmentIds == [7]


def test_subtitle_sorts_out_of_order_segments_and_warns(
    tmp_path: Path,
    caplog,
) -> None:
    caplog.set_level(logging.WARNING, logger="pipeline.subtitle")

    record, _ = _run_pipeline(
        tmp_path,
        segments=[
            TranslationSegment(
                id=2,
                start=4.0,
                end=6.0,
                source="Later.",
                target="後の字幕です。",
            ),
            TranslationSegment(
                id=1,
                start=0.0,
                end=2.0,
                source="Earlier.",
                target="先の字幕です。",
            ),
        ],
    )

    subtitles = read_subtitles(record.project_dir)

    assert [cue.segmentIds for cue in subtitles.cues] == [[1], [2]]
    assert all(cue.start <= cue.end for cue in subtitles.cues)
    assert [cue.start for cue in subtitles.cues] == sorted(cue.start for cue in subtitles.cues)
    assert _has_no_overlaps(subtitles.cues)
    assert len(
        [
            record
            for record in caplog.records
            if record.name == "pipeline.subtitle"
            and "Translation segments are not sorted by start time" in record.message
        ]
    ) == 1


def _run_pipeline(
    tmp_path: Path,
    *,
    segments: Optional[list[TranslationSegment]] = None,
) -> tuple[JobRecord, list]:
    config = BackendConfig().with_projects_dir(tmp_path)
    store = JobStore(config.projects_dir)
    record = store.create("/tmp/input.mp4", default_job_settings(config))
    translation = Translation(
        model=record.settings.translate.model,
        sourceLanguage="en",
        targetLanguage="ja",
        segments=segments
        if segments is not None
        else [
            TranslationSegment(
                id=0,
                start=0.0,
                end=2.0,
                source="Hello.",
                target="こんにちは。",
            )
        ],
    )
    write_translation(record.project_dir, translation)

    notifications = []
    runner = PipelineRunner(
        config,
        store,
        [
            SubtitleStage(),
            StubStage(StageName.tts, "tts/cue_0000.wav"),
            StubStage(StageName.mix, "voiceover.wav"),
        ],
        lambda job: notifications.append(job.snapshot()),
    )

    runner.run(record)
    return record, notifications


def _has_no_overlaps(cues) -> bool:
    return all(current.end <= following.start for current, following in zip(cues, cues[1:]))
