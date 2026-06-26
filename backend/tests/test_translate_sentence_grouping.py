from __future__ import annotations

from pipeline.translate import group_segments_by_sentence
from schemas.artifacts import TranscriptSegment


def test_groups_multiple_segments_until_sentence_boundary() -> None:
    groups = group_segments_by_sentence(
        [
            _segment(1, 0.0, 1.0, "This is"),
            _segment(2, 1.0, 2.0, "one sentence."),
            _segment(3, 2.0, 3.0, "Next one."),
        ]
    )

    assert [[segment.id for segment in group] for group in groups] == [[1, 2], [3]]


def test_group_identity_and_timing_come_from_first_and_last_segments() -> None:
    groups = group_segments_by_sentence(
        [
            _segment(10, 3.5, 4.0, "A sentence"),
            _segment(11, 4.0, 5.25, "split here!"),
        ]
    )

    group = groups[0]
    assert group[0].id == 10
    assert group[0].start == 3.5
    assert group[-1].end == 5.25


def test_non_linguistic_segment_is_isolated() -> None:
    groups = group_segments_by_sentence(
        [
            _segment(1, 0.0, 1.0, "Before"),
            _segment(2, 1.0, 2.0, "..."),
            _segment(3, 2.0, 3.0, "after."),
        ]
    )

    assert [[segment.id for segment in group] for group in groups] == [[1], [2], [3]]


def test_empty_source_segment_is_isolated() -> None:
    groups = group_segments_by_sentence(
        [
            _segment(1, 0.0, 1.0, "Before"),
            _segment(2, 1.0, 2.0, "   "),
            _segment(3, 2.0, 3.0, "after."),
        ]
    )

    assert [[segment.id for segment in group] for group in groups] == [[1], [2], [3]]


def test_single_segment_sentence_with_terminal_punctuation_closes_group() -> None:
    groups = group_segments_by_sentence([_segment(1, 0.0, 1.0, 'Finished."')])

    assert [[segment.id for segment in group] for group in groups] == [[1]]


def test_final_group_closes_without_terminal_punctuation() -> None:
    groups = group_segments_by_sentence(
        [
            _segment(1, 0.0, 1.0, "This sentence"),
            _segment(2, 1.0, 2.0, "has no terminator"),
        ]
    )

    assert [[segment.id for segment in group] for group in groups] == [[1, 2]]


def _segment(segment_id: int, start: float, end: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(id=segment_id, start=start, end=end, text=text)
