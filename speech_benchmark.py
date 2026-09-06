"""Content-safe speech-timing benchmark and debug-trace analyzer.

The fixture gate deliberately calls the same timing functions as the TUI. The
trace analyzer consumes only structural diagnostics, so a live profile can be
compared without retaining prompts, response text, or audio.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from timing import normalize_speech_timing, visible_text


@dataclass(frozen=True)
class BenchmarkWord:
    text: str
    start_ms: int
    end_ms: int

    def as_payload(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
        }


@dataclass(frozen=True)
class BenchmarkSegment:
    segment_id: str
    spoken_text: str
    offset_ms: int
    duration_ms: int
    timing_source: str = "alignment"
    words: tuple[BenchmarkWord, ...] = ()
    fallback_reason: str | None = None
    failure_class: str | None = None

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "segment_id": self.segment_id,
            "text": self.spoken_text,
            "audio_offset_ms": self.offset_ms,
            "duration_ms": self.duration_ms,
            "timing_source": self.timing_source,
            "words": [word.as_payload() for word in self.words],
        }
        if self.fallback_reason is not None:
            payload["fallback_reason"] = self.fallback_reason
        return payload


@dataclass(frozen=True)
class BenchmarkFixture:
    name: str
    target_text: str
    segments: tuple[BenchmarkSegment, ...]
    first_audio_latency_ms: int


@dataclass(frozen=True)
class FixtureResult:
    name: str
    passed: bool
    aligned_segments: int
    fallback_segments: int
    aligned_words: int
    expected_words: int
    fallback_reasons: dict[str, int]
    failure_classes: dict[str, int]
    first_audio_latency_ms: int
    audio_duration_ms: int
    offsets_monotonic: bool
    audio_bounded: bool
    no_blank_transcript: bool
    no_backward_visible_text: bool
    no_repeated_paragraph: bool
    final_text_complete: bool

    @property
    def alignment_coverage(self) -> float:
        if self.expected_words <= 0:
            return 0.0
        return self.aligned_words / self.expected_words

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "aligned_segments": self.aligned_segments,
            "fallback_segments": self.fallback_segments,
            "aligned_words": self.aligned_words,
            "expected_words": self.expected_words,
            "alignment_coverage": round(self.alignment_coverage, 4),
            "fallback_reasons": dict(sorted(self.fallback_reasons.items())),
            "failure_classes": dict(sorted(self.failure_classes.items())),
            "first_audio_latency_ms": self.first_audio_latency_ms,
            "audio_duration_ms": self.audio_duration_ms,
            "offsets_monotonic": self.offsets_monotonic,
            "audio_bounded": self.audio_bounded,
            "no_blank_transcript": self.no_blank_transcript,
            "no_backward_visible_text": self.no_backward_visible_text,
            "no_repeated_paragraph": self.no_repeated_paragraph,
            "final_text_complete": self.final_text_complete,
        }


@dataclass(frozen=True)
class FixtureReport:
    results: tuple[FixtureResult, ...]

    @property
    def fixture_count(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(result.passed for result in self.results)

    @property
    def aligned_segments(self) -> int:
        return sum(result.aligned_segments for result in self.results)

    @property
    def fallback_segments(self) -> int:
        return sum(result.fallback_segments for result in self.results)

    @property
    def aligned_words(self) -> int:
        return sum(result.aligned_words for result in self.results)

    @property
    def expected_words(self) -> int:
        return sum(result.expected_words for result in self.results)

    @property
    def alignment_coverage(self) -> float:
        if self.expected_words <= 0:
            return 0.0
        return self.aligned_words / self.expected_words

    @property
    def fallback_reasons(self) -> dict[str, int]:
        return dict(
            sorted(
                Counter(
                    reason
                    for result in self.results
                    for reason, count in result.fallback_reasons.items()
                    for _ in range(count)
                ).items()
            )
        )

    @property
    def failure_classes(self) -> dict[str, int]:
        return dict(
            sorted(
                Counter(
                    failure
                    for result in self.results
                    for failure, count in result.failure_classes.items()
                    for _ in range(count)
                ).items()
            )
        )

    @property
    def first_audio_latency_ms(self) -> dict[str, int | float]:
        values = [result.first_audio_latency_ms for result in self.results]
        return {
            "min": min(values),
            "max": max(values),
            "mean": round(statistics.mean(values), 1),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "fixture_count": self.fixture_count,
            "aligned_segments": self.aligned_segments,
            "fallback_segments": self.fallback_segments,
            "aligned_words": self.aligned_words,
            "expected_words": self.expected_words,
            "alignment_coverage": round(self.alignment_coverage, 4),
            "fallback_reasons": self.fallback_reasons,
            "failure_classes": self.failure_classes,
            "first_audio_latency_ms": self.first_audio_latency_ms,
            "results": [result.as_dict() for result in self.results],
        }


@dataclass(frozen=True)
class TraceReport:
    label: str
    turn_count: int
    audio_stream_count: int
    first_audio_latency_ms: tuple[int, ...]
    timing_segments: int
    aligned_segments: int
    fallback_segments: int
    fallback_reasons: dict[str, int]
    total_audio_duration_ms: int
    offsets_monotonic: bool
    timing_parse_failures: int
    non_monotonic_turns: tuple[int, ...]

    @property
    def passed(self) -> bool:
        return (
            self.turn_count > 0
            and self.audio_stream_count > 0
            and self.timing_parse_failures == 0
            and self.offsets_monotonic
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "passed": self.passed,
            "turn_count": self.turn_count,
            "audio_stream_count": self.audio_stream_count,
            "first_audio_latency_ms": list(self.first_audio_latency_ms),
            "timing_segments": self.timing_segments,
            "aligned_segments": self.aligned_segments,
            "fallback_segments": self.fallback_segments,
            "fallback_reasons": dict(sorted(self.fallback_reasons.items())),
            "total_audio_duration_ms": self.total_audio_duration_ms,
            "offsets_monotonic": self.offsets_monotonic,
            "timing_parse_failures": self.timing_parse_failures,
            "non_monotonic_turns": list(self.non_monotonic_turns),
        }


def _word_count(text: str) -> int:
    return sum(
        bool("".join(character.lower() for character in token if character.isalnum()))
        for token in text.split()
    )


def _even_words(text: str, offset_ms: int, duration_ms: int) -> tuple[BenchmarkWord, ...]:
    tokens = tuple(token for token in text.split() if token)
    if not tokens:
        return ()
    return tuple(
        BenchmarkWord(
            text=token,
            start_ms=offset_ms + (duration_ms * index) // len(tokens),
            end_ms=offset_ms + (duration_ms * (index + 1)) // len(tokens),
        )
        for index, token in enumerate(tokens)
    )


def _aligned(
    segment_id: str,
    text: str,
    offset_ms: int,
    duration_ms: int,
) -> BenchmarkSegment:
    return BenchmarkSegment(
        segment_id=segment_id,
        spoken_text=text,
        offset_ms=offset_ms,
        duration_ms=duration_ms,
        words=_even_words(text, offset_ms, duration_ms),
    )


def _fallback(
    segment_id: str,
    text: str,
    offset_ms: int,
    duration_ms: int,
    reason: str,
    failure_class: str | None = None,
) -> BenchmarkSegment:
    return BenchmarkSegment(
        segment_id=segment_id,
        spoken_text=text,
        offset_ms=offset_ms,
        duration_ms=duration_ms,
        timing_source="duration_fallback",
        fallback_reason=reason,
        failure_class=failure_class,
    )


def fixture_corpus() -> tuple[BenchmarkFixture, ...]:
    """Return the fixed matrix used by the rollout gate."""
    malformed = BenchmarkSegment(
        segment_id="malformed",
        spoken_text="Malformed spans become safe fallback.",
        offset_ms=0,
        duration_ms=1200,
        words=(
            BenchmarkWord("Malformed", 0, 300),
            BenchmarkWord("spans", 300, 900),
            BenchmarkWord("become", 900, 1300),
            BenchmarkWord("safe", 1300, 1400),
            BenchmarkWord("fallback.", 1400, 1500),
        ),
        failure_class="invalid_spans",
    )
    return (
        BenchmarkFixture(
            "short_sentence",
            "The timing is precise.",
            (_aligned("short", "The timing is precise.", 0, 1200),),
            180,
        ),
        BenchmarkFixture(
            "long_answer_fallback",
            "A long answer keeps speaking while the client uses safe duration pacing for every segment in the response.",
            (
                _fallback(
                    "long",
                    "A long answer keeps speaking while the client uses safe duration pacing for every segment in the response.",
                    0,
                    4800,
                    "error",
                ),
            ),
            220,
        ),
        BenchmarkFixture(
            "markdown_paragraphs",
            "**Hermes** keeps\nmoving.\n\nThe TARDIS waits.",
            (
                _aligned("markdown-1", "Hermes keeps moving.", 0, 1500),
                _aligned("markdown-2", "The TARDIS waits.", 1500, 1400),
            ),
            240,
        ),
        BenchmarkFixture(
            "punctuation_numbers",
            "Version 2.0 is ready, 42 times.",
            (_aligned("numbers", "Version 2.0 is ready, 42 times.", 0, 1800),),
            280,
        ),
        BenchmarkFixture(
            "multi_segment_fallback",
            "First clause.\n\nSecond clause with 42.",
            (
                _aligned("multi-1", "First clause.", 0, 800),
                _fallback("multi-2", "Second clause with 42.", 800, 1600, "disabled"),
            ),
            300,
        ),
        BenchmarkFixture(
            "malformed_alignment",
            "Malformed spans become safe fallback.",
            (malformed,),
            360,
        ),
        BenchmarkFixture(
            "provider_422",
            "The provider rejected this long alignment request.",
            (
                _fallback(
                    "provider-422",
                    "The provider rejected this long alignment request.",
                    0,
                    2200,
                    "error",
                    "provider_422",
                ),
            ),
            400,
        ),
        BenchmarkFixture(
            "alignment_timeout",
            "The aligner timed out and duration pacing continued.",
            (
                _fallback(
                    "timeout",
                    "The aligner timed out and duration pacing continued.",
                    0,
                    2100,
                    "timeout",
                    "timeout",
                ),
            ),
            420,
        ),
    )


def _first_word_prefix(text: str) -> str:
    end = 0
    while end < len(text) and not text[end].isspace():
        end += 1
    while end < len(text) and text[end].isspace():
        end += 1
    return text[:end]


def run_fixture(fixture: BenchmarkFixture) -> FixtureResult:
    timings = tuple(
        normalize_speech_timing(segment.payload()) for segment in fixture.segments
    )
    if any(timing is None for timing in timings):
        raise ValueError(f"fixture {fixture.name} generated unsafe timing geometry")
    safe_timings = tuple(timing for timing in timings if timing is not None)
    offsets = [timing.audio_offset for timing in safe_timings]
    audio_duration_ms = round(max(timing.end for timing in safe_timings) * 1000)
    offsets_monotonic = offsets == sorted(offsets)
    audio_bounded = all(
        timing.audio_offset >= 0
        and timing.duration > 0
        and timing.end <= audio_duration_ms / 1000 + 1e-9
        for timing in safe_timings
    )

    no_blank_transcript = True
    no_backward_visible_text = True
    previous_visible = ""
    sample_count = max(1, math.ceil(audio_duration_ms / 50))
    for index in range(1, sample_count + 1):
        position = min(audio_duration_ms / 1000, index * 0.05)
        candidate = visible_text(fixture.target_text, safe_timings, position)
        active = any(
            timing.audio_offset < position <= timing.end for timing in safe_timings
        )
        if active and not candidate:
            candidate = _first_word_prefix(fixture.target_text)
        if active and not candidate:
            no_blank_transcript = False
        if len(candidate) < len(previous_visible):
            no_backward_visible_text = False
        previous_visible = candidate

    final_visible = visible_text(
        fixture.target_text,
        safe_timings,
        audio_duration_ms / 1000 + 0.001,
    )
    no_repeated_paragraph = all(
        not paragraph or final_visible.count(paragraph) <= 1
        for paragraph in fixture.target_text.split("\n\n")
    )
    final_text_complete = final_visible == fixture.target_text

    fallback_reasons = Counter(
        timing.fallback_reason
        for timing in safe_timings
        if timing.fallback_reason
    )
    failure_classes = Counter(
        segment.failure_class
        for segment, timing in zip(fixture.segments, safe_timings)
        if segment.failure_class and timing.timing_source == "duration_fallback"
    )
    aligned_segments = sum(timing.uses_word_timing for timing in safe_timings)
    aligned_words = sum(len(timing.words) for timing in safe_timings)
    expected_words = sum(_word_count(segment.spoken_text) for segment in fixture.segments)
    passed = all(
        (
            offsets_monotonic,
            audio_bounded,
            no_blank_transcript,
            no_backward_visible_text,
            no_repeated_paragraph,
            final_text_complete,
        )
    )
    return FixtureResult(
        name=fixture.name,
        passed=passed,
        aligned_segments=aligned_segments,
        fallback_segments=len(safe_timings) - aligned_segments,
        aligned_words=aligned_words,
        expected_words=expected_words,
        fallback_reasons=dict(fallback_reasons),
        failure_classes=dict(failure_classes),
        first_audio_latency_ms=fixture.first_audio_latency_ms,
        audio_duration_ms=audio_duration_ms,
        offsets_monotonic=offsets_monotonic,
        audio_bounded=audio_bounded,
        no_blank_transcript=no_blank_transcript,
        no_backward_visible_text=no_backward_visible_text,
        no_repeated_paragraph=no_repeated_paragraph,
        final_text_complete=final_text_complete,
    )


def run_fixtures(fixtures: Iterable[BenchmarkFixture] | None = None) -> FixtureReport:
    return FixtureReport(tuple(run_fixture(fixture) for fixture in (fixtures or fixture_corpus())))


_TURN_SEND = re.compile(r"turn\.send(?:\s+mono_ms=(?P<mono>\d+))?")
_STREAM_STARTED = re.compile(r"audio\.stream\.started\s+mono_ms=(?P<mono>\d+)")
_TURN_INDEX = re.compile(r"turn_index=(?P<index>\d+)")
_TIMING = re.compile(
    r"audio\.speech_timing.*?offset_ms=(?P<offset>\d+)\s+"
    r"duration_ms=(?P<duration>\d+)\s+source=(?P<source>\S+)\s+"
    r"words=(?P<words>-?\d+)\s+fallback=(?P<fallback>\S+)"
)
_RECEIVED_AUDIO = re.compile(r"received_audio_ms=(?P<audio>\d+)")


def analyze_trace(lines: Iterable[str], *, label: str = "trace") -> TraceReport:
    send_times: list[int] = []
    stream_times: list[int] = []
    timing_offsets: dict[int, list[int]] = {}
    fallback_reasons: Counter[str] = Counter()
    timing_segments = 0
    aligned_segments = 0
    fallback_segments = 0
    total_audio_duration_ms = 0
    timing_parse_failures = 0
    turn_count = 0

    for line in lines:
        send_match = _TURN_SEND.search(line)
        if send_match:
            turn_count += 1
            if send_match.group("mono") is not None:
                send_times.append(int(send_match.group("mono")))

        stream_match = _STREAM_STARTED.search(line)
        if stream_match:
            stream_times.append(int(stream_match.group("mono")))

        received_match = _RECEIVED_AUDIO.search(line)
        if received_match:
            total_audio_duration_ms = max(
                total_audio_duration_ms,
                int(received_match.group("audio")),
            )

        if "audio.speech_timing" not in line:
            continue
        timing_match = _TIMING.search(line)
        if timing_match is None:
            timing_parse_failures += 1
            continue
        timing_segments += 1
        turn_index_match = _TURN_INDEX.search(line)
        turn_index = int(turn_index_match.group("index")) if turn_index_match else 0
        timing_offsets.setdefault(turn_index, []).append(
            int(timing_match.group("offset"))
        )
        source = timing_match.group("source")
        if source == "alignment":
            aligned_segments += 1
        else:
            fallback_segments += 1
            fallback = timing_match.group("fallback")
            if fallback != "none":
                fallback_reasons[fallback] += 1

    latencies = tuple(
        stream - send
        for send, stream in zip(send_times, stream_times)
        if stream >= send
    )
    non_monotonic_turns = tuple(
        sorted(
            turn_index
            for turn_index, offsets in timing_offsets.items()
            if offsets != sorted(offsets)
        )
    )
    offsets_monotonic = not non_monotonic_turns
    return TraceReport(
        label=label,
        turn_count=turn_count,
        audio_stream_count=len(stream_times),
        first_audio_latency_ms=latencies,
        timing_segments=timing_segments,
        aligned_segments=aligned_segments,
        fallback_segments=fallback_segments,
        fallback_reasons=dict(fallback_reasons),
        total_audio_duration_ms=total_audio_duration_ms,
        offsets_monotonic=offsets_monotonic,
        timing_parse_failures=timing_parse_failures,
        non_monotonic_turns=non_monotonic_turns,
    )


def analyze_trace_file(path: Path, *, label: str | None = None) -> TraceReport:
    with path.open("r", encoding="utf-8") as stream:
        return analyze_trace(stream, label=label or path.stem)


def _log_spec(value: str) -> tuple[str, Path]:
    if "=" in value:
        label, raw_path = value.split("=", 1)
        if label and raw_path:
            return label, Path(raw_path)
    path = Path(value)
    return path.stem, path


def _human_fixture_report(report: FixtureReport) -> str:
    status = "PASS" if report.passed else "FAIL"
    latency = report.first_audio_latency_ms
    return (
        f"fixtures: {status} ({report.fixture_count}) | "
        f"alignment coverage={report.alignment_coverage:.1%} | "
        f"fallback segments={report.fallback_segments} | "
        f"first audio ms={latency['min']}-{latency['max']}"
    )


def _human_trace_report(report: TraceReport) -> str:
    status = "PASS" if report.passed else "FAIL"
    latency = ",".join(str(value) for value in report.first_audio_latency_ms) or "n/a"
    return (
        f"log[{report.label}]: {status} | turns={report.turn_count} | "
        f"first audio ms={latency} | timing segments={report.timing_segments} | "
        f"aligned={report.aligned_segments} fallback={report.fallback_segments} | "
        f"audio ms={report.total_audio_duration_ms} | "
        f"offsets={'PASS' if report.offsets_monotonic else 'FAIL'} | "
        f"parse failures={report.timing_parse_failures}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log",
        action="append",
        default=[],
        metavar="[LABEL=]PATH",
        help="analyze a content-safe debug trace; repeat for local and media",
    )
    parser.add_argument(
        "--fixtures",
        action="store_true",
        help="run deterministic fixtures (the default unless --logs-only is used)",
    )
    parser.add_argument(
        "--logs-only",
        action="store_true",
        help="skip deterministic fixtures and analyze only --log inputs",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable metrics")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="require at least one live log and fail on any failed report",
    )
    args = parser.parse_args(argv)

    fixture_report = None if args.logs_only else run_fixtures()
    trace_reports = []
    for value in args.log:
        label, path = _log_spec(value)
        trace_reports.append(analyze_trace_file(path, label=label))

    passed = (fixture_report is None or fixture_report.passed) and all(
        report.passed for report in trace_reports
    )
    if args.strict and not trace_reports:
        passed = False

    if args.json:
        payload: dict[str, Any] = {"passed": passed, "logs": [report.as_dict() for report in trace_reports]}
        if fixture_report is not None:
            payload["fixtures"] = fixture_report.as_dict()
        print(json.dumps(payload, sort_keys=True))
    else:
        if fixture_report is not None:
            print(_human_fixture_report(fixture_report))
        for report in trace_reports:
            print(_human_trace_report(report))
        print("gate: " + ("PASS" if passed else "FAIL"))
    return 0 if passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
