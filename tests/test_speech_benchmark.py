import json

from speech_benchmark import (
    analyze_trace,
    fixture_corpus,
    main,
    run_fixtures,
)


def test_fixture_corpus_covers_the_rollout_matrix():
    names = {fixture.name for fixture in fixture_corpus()}

    assert names == {
        "short_sentence",
        "long_answer_fallback",
        "markdown_paragraphs",
        "punctuation_numbers",
        "multi_segment_fallback",
        "malformed_alignment",
        "provider_422",
        "alignment_timeout",
    }


def test_fixture_gate_reuses_the_real_timing_contract_and_passes():
    report = run_fixtures()

    assert report.passed is True
    assert report.fixture_count == 8
    assert report.aligned_segments > 0
    assert report.fallback_segments > 0
    assert report.alignment_coverage < 1.0
    assert report.failure_classes == {
        "invalid_spans": 1,
        "provider_422": 1,
        "timeout": 1,
    }
    assert all(result.passed for result in report.results)


def test_fixture_report_is_content_safe_json():
    report = run_fixtures()
    encoded = json.dumps(report.as_dict())

    assert "Hermes keeps" not in encoded
    assert "private" not in encoded
    assert report.as_dict()["first_audio_latency_ms"] == {
        "min": 180,
        "max": 420,
        "mean": 300.0,
    }


def test_trace_analyzer_extracts_metrics_without_response_content():
    report = analyze_trace(
        [
            "2026-09-05 DEBUG hermes_relay_tui.client turn.send "
            "mono_ms=100 turn_id=t1 session_id=s stt_source=local "
            "text_len=22 sha256=deadbeef",
            "2026-09-05 DEBUG hermes_relay_tui app audio.stream.started "
            "mono_ms=280 turn_index=0 sample_rate=24000 channels=1 "
            "sample_width=2 active=True",
            "2026-09-05 DEBUG hermes_relay_tui app audio.chunk.received "
            "mono_ms=300 turn_index=0 segment_index=0 chunk_index=1 "
            "bytes=8192 received_bytes=8192 received_audio_ms=170 "
            "playback_position_ms=0 queued_audio_ms=170 active=True",
            "2026-09-05 DEBUG hermes_relay_tui app audio.speech_timing "
            "mono_ms=310 turn_index=0 segment_id=len=9 sha256=abc "
            "offset_ms=0 duration_ms=170 source=alignment words=3 "
            "fallback=none received_audio_ms=170 playback_position_ms=0 "
            "queued_audio_ms=170",
            "2026-09-05 DEBUG hermes_relay_tui app audio.segment.end "
            "mono_ms=500 turn_index=0 segment_index=0 received_bytes=8192 "
            "received_audio_ms=170 playback_position_ms=170 "
            "queued_audio_ms=0 active=False",
        ],
        label="local",
    )

    assert report.passed is True
    assert report.label == "local"
    assert report.first_audio_latency_ms == (180,)
    assert report.aligned_segments == 1
    assert report.fallback_segments == 0
    assert report.total_audio_duration_ms == 170
    assert report.offsets_monotonic is True
    assert report.as_dict()["label"] == "local"
    assert "turn_id" not in json.dumps(report.as_dict())


def test_trace_analyzer_rejects_non_monotonic_offsets_and_bad_timing_lines():
    report = analyze_trace(
        [
            "turn.send mono_ms=10 turn_id=t1",
            "audio.stream.started mono_ms=20 turn_index=0 sample_rate=24000 "
            "channels=1 sample_width=2 active=True",
            "audio.speech_timing mono_ms=30 turn_index=0 segment_id=len=1 "
            "offset_ms=500 duration_ms=200 source=alignment words=1 "
            "fallback=none received_audio_ms=700 playback_position_ms=0 "
            "queued_audio_ms=700",
            "audio.speech_timing mono_ms=40 turn_index=0 segment_id=len=1 "
            "offset_ms=0 duration_ms=200 source=duration_fallback words=0 "
            "fallback=invalid received_audio_ms=700 playback_position_ms=0 "
            "queued_audio_ms=700",
            "audio.speech_timing missing geometry",
        ]
    )

    assert report.passed is False
    assert report.offsets_monotonic is False
    assert report.timing_parse_failures == 1
    assert report.non_monotonic_turns == (0,)


def test_trace_analyzer_resets_offset_order_at_each_turn():
    report = analyze_trace(
        [
            "turn.send mono_ms=10 turn_id=t1",
            "audio.stream.started mono_ms=20 turn_index=0 sample_rate=24000 "
            "channels=1 sample_width=2 active=True",
            "audio.speech_timing mono_ms=30 turn_index=0 segment_id=len=1 "
            "offset_ms=0 duration_ms=200 source=alignment words=1 fallback=none "
            "received_audio_ms=200 playback_position_ms=0 queued_audio_ms=200",
            "turn.send mono_ms=400 turn_id=t2",
            "audio.stream.started mono_ms=410 turn_index=1 sample_rate=24000 "
            "channels=1 sample_width=2 active=True",
            "audio.speech_timing mono_ms=420 turn_index=1 segment_id=len=1 "
            "offset_ms=0 duration_ms=200 source=alignment words=1 fallback=none "
            "received_audio_ms=200 playback_position_ms=0 queued_audio_ms=200",
        ]
    )

    assert report.passed is True
    assert report.offsets_monotonic is True
    assert report.non_monotonic_turns == ()


def test_cli_emits_content_safe_json(capsys):
    assert main(["--fixtures", "--json"]) == 0

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["passed"] is True
    assert payload["fixtures"]["fixture_count"] == 8
    assert "Hermes keeps" not in output
