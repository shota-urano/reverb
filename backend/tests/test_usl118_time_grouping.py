from __future__ import annotations

from pipeline.translate import group_segments_by_sentence
from test_translate_sentence_grouping import _segment


def test_bundles_short_terminal_segments_up_to_target_duration() -> None:
    segments = [
        _segment(index, float(index - 1), float(index), f"Sentence {index}.")
        for index in range(1, 7)
    ]

    groups = group_segments_by_sentence(segments, target_seconds=8.0, gap_seconds=1.0)

    assert [[segment.id for segment in group] for group in groups] == [[1, 2, 3, 4, 5, 6]]


def test_silence_gap_splits_terminal_segment_groups() -> None:
    segments = [
        _segment(1, 0.0, 1.0, "Sentence 1."),
        _segment(2, 1.0, 2.0, "Sentence 2."),
        _segment(3, 2.0, 3.0, "Sentence 3."),
        _segment(4, 4.5, 5.5, "Sentence 4."),
        _segment(5, 5.5, 6.5, "Sentence 5."),
        _segment(6, 6.5, 7.5, "Sentence 6."),
    ]

    groups = group_segments_by_sentence(segments, target_seconds=8.0, gap_seconds=1.0)

    assert [[segment.id for segment in group] for group in groups] == [[1, 2, 3], [4, 5, 6]]


def test_non_linguistic_segment_is_a_solo_hard_boundary() -> None:
    groups = group_segments_by_sentence(
        [
            _segment(1, 0.0, 1.0, "Before."),
            _segment(2, 1.0, 2.0, "..."),
            _segment(3, 2.0, 3.0, "After."),
        ],
        target_seconds=8.0,
        gap_seconds=1.0,
    )

    assert [[segment.id for segment in group] for group in groups] == [[1], [2], [3]]


def test_target_and_gap_thresholds_are_controllable_per_call() -> None:
    contiguous = [
        _segment(1, 0.0, 1.0, "One."),
        _segment(2, 1.0, 2.0, "Two."),
        _segment(3, 2.0, 3.0, "Three."),
    ]
    with_gap = [
        _segment(1, 0.0, 1.0, "One."),
        _segment(2, 1.5, 2.5, "Two."),
    ]

    target_groups = group_segments_by_sentence(
        contiguous,
        target_seconds=2.5,
        gap_seconds=1.0,
    )
    gap_groups = group_segments_by_sentence(with_gap, target_seconds=8.0, gap_seconds=0.25)

    assert [[segment.id for segment in group] for group in target_groups] == [[1, 2], [3]]
    assert [[segment.id for segment in group] for group in gap_groups] == [[1], [2]]


def test_non_terminal_segments_accumulate_regardless_of_target_duration() -> None:
    groups = group_segments_by_sentence(
        [
            _segment(1, 0.0, 2.0, "This keeps"),
            _segment(2, 2.0, 4.0, "going without"),
            _segment(3, 4.0, 6.0, "terminal punctuation"),
        ],
        target_seconds=1.0,
        gap_seconds=1.0,
    )

    assert [[segment.id for segment in group] for group in groups] == [[1, 2, 3]]
