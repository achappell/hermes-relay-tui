from timing import (
    SpeechTiming,
    duration_visible_text,
    fallback_visible_text,
    longest_valid_prefix,
    normalize_speech_timing,
    visible_text,
)


def aligned_timing() -> SpeechTiming:
    timing = normalize_speech_timing(
        {
            "segment_id": "segment-1",
            "text": "Hermes keeps moving.",
            "timing_source": "alignment",
            "audio_offset_ms": 0,
            "duration_ms": 1300,
            "words": [
                {"text": "Hermes", "start_ms": 0, "end_ms": 280},
                {"text": "keeps", "start_ms": 280, "end_ms": 510},
                {"text": "moving.", "start_ms": 510, "end_ms": 1300},
            ],
        }
    )
    assert timing is not None
    return timing


def test_visible_text_reveals_aligned_words_at_playback_position():
    timing = aligned_timing()

    assert visible_text("Hermes keeps moving.", [timing], 0.0) == "Hermes "
    assert visible_text("Hermes keeps moving.", [timing], 0.5) == "Hermes keeps "
    assert visible_text("Hermes keeps moving.", [timing], 1.3) == "Hermes keeps moving."


def test_duration_visible_text_reveals_a_known_audio_duration():
    assert duration_visible_text("one two three four", 0.0, 2.0) == ""
    assert duration_visible_text("one two three four", 0.5, 2.0) == "one "
    assert duration_visible_text("one two three four", 1.5, 2.0) == "one two three "
    assert duration_visible_text("one two three four", 2.0, 2.0) == "one two three four"


def test_fallback_visible_text_advances_without_waiting_for_segment_timing():
    target = "one two three four five six"

    assert fallback_visible_text(target, 0.0, words_per_second=2.0) == ""
    assert fallback_visible_text(target, 0.5, words_per_second=2.0) == "one "
    assert fallback_visible_text(target, 1.1, words_per_second=2.0) == "one two three "
    assert fallback_visible_text(target, 3.0, words_per_second=2.0) == target


def test_longest_valid_prefix_rejects_revisions_that_leave_the_target():
    assert longest_valid_prefix(
        "Hermes keeps moving.",
        ["Hermes ", "Hermes keeps ", "different answer"],
    ) == "Hermes keeps "


def test_normalized_event_can_be_rehydrated_as_typed_timing():
    timing = aligned_timing()

    assert SpeechTiming.from_event(timing.as_event()) == timing


def test_visible_text_orders_segments_and_skips_an_unmappable_middle_segment():
    first = normalize_speech_timing(
        {
            "segment_id": "segment-1",
            "text": "one two",
            "timing_source": "alignment",
            "audio_offset_ms": 0,
            "duration_ms": 500,
            "words": [
                {"text": "one", "start_ms": 0, "end_ms": 250},
                {"text": "two", "start_ms": 250, "end_ms": 500},
            ],
        }
    )
    middle = normalize_speech_timing(
        {
            "segment_id": "segment-2",
            "text": "spoken rewrite",
            "timing_source": "duration_fallback",
            "audio_offset_ms": 500,
            "duration_ms": 500,
            "fallback_reason": "error",
        }
    )
    last = normalize_speech_timing(
        {
            "segment_id": "segment-3",
            "text": "four five",
            "timing_source": "alignment",
            "audio_offset_ms": 1000,
            "duration_ms": 500,
            "words": [
                {"text": "four", "start_ms": 1000, "end_ms": 1250},
                {"text": "five", "start_ms": 1250, "end_ms": 1500},
            ],
        }
    )
    assert first is not None and middle is not None and last is not None

    assert visible_text("one two three four five", [last, middle, first], 0.75) == "one two "
    assert visible_text("one two three four five", [last, middle, first], 1.5) == "one two three four five"


def test_visible_text_uses_the_latest_revision_for_a_segment_id():
    initial = normalize_speech_timing(
        {
            "segment_id": "segment-1",
            "text": "one",
            "timing_source": "alignment",
            "audio_offset_ms": 0,
            "duration_ms": 500,
            "words": [{"text": "one", "start_ms": 0, "end_ms": 500}],
        }
    )
    revised = normalize_speech_timing(
        {
            "segment_id": "segment-1",
            "text": "one two",
            "timing_source": "alignment",
            "audio_offset_ms": 0,
            "duration_ms": 1000,
            "words": [
                {"text": "one", "start_ms": 0, "end_ms": 500},
                {"text": "two", "start_ms": 500, "end_ms": 1000},
            ],
        }
    )
    assert initial is not None and revised is not None

    assert visible_text("one two", [initial, revised], 0.75) == "one two"


def test_visible_text_maps_punctuation_and_markdown_to_the_rendered_prefix():
    timing = normalize_speech_timing(
        {
            "segment_id": "segment-1",
            "text": "Hermes, keeps moving",
            "timing_source": "alignment",
            "audio_offset_ms": 0,
            "duration_ms": 900,
            "words": [
                {"text": "Hermes,", "start_ms": 0, "end_ms": 280},
                {"text": "keeps", "start_ms": 280, "end_ms": 510},
                {"text": "moving", "start_ms": 510, "end_ms": 900},
            ],
        }
    )
    assert timing is not None

    assert visible_text("**Hermes** keeps\nmoving.", [timing], 0.9) == "**Hermes** keeps\nmoving."
