"""Speech timing data and deterministic caption reveal helpers.

The relay sends timing in milliseconds, while local playback and caption
reveal use seconds.  Keeping the conversion and validation here gives every
front end the same safe contract without pulling a UI framework into the
session core.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable


_FALLBACK_REASONS = {"disabled", "unsupported", "missing", "error", "timeout", "invalid"}
DEFAULT_FALLBACK_WORDS_PER_SECOND = 2.8


@dataclass(frozen=True)
class SpeechTimingWord:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class SpeechTiming:
    segment_id: str
    text: str
    timing_source: str
    audio_offset: float
    duration: float
    fallback_reason: str | None
    words: tuple[SpeechTimingWord, ...] = ()

    @property
    def end(self) -> float:
        return self.audio_offset + self.duration

    @property
    def uses_word_timing(self) -> bool:
        return self.timing_source == "alignment" and bool(self.words)

    def as_event(self) -> dict[str, Any]:
        return {
            "type": "speech_timing",
            "segment_id": self.segment_id,
            "text": self.text,
            "timing_source": self.timing_source,
            "audio_offset": self.audio_offset,
            "duration": self.duration,
            "fallback_reason": self.fallback_reason,
            "words": [
                {"text": word.text, "start": word.start, "end": word.end}
                for word in self.words
            ],
        }

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> "SpeechTiming":
        return cls(
            segment_id=str(event.get("segment_id") or ""),
            text=str(event.get("text") or ""),
            timing_source=str(event.get("timing_source") or "duration_fallback"),
            audio_offset=float(event.get("audio_offset") or 0.0),
            duration=float(event.get("duration") or 0.0),
            fallback_reason=event.get("fallback_reason") or None,
            words=tuple(
                SpeechTimingWord(
                    text=str(word.get("text") or ""),
                    start=float(word.get("start") or 0.0),
                    end=float(word.get("end") or 0.0),
                )
                for word in event.get("words", [])
                if isinstance(word, dict)
            ),
        )


def normalize_speech_timing(payload: dict[str, Any]) -> SpeechTiming | None:
    """Normalize one wire record, degrading unsafe alignment to duration pacing."""
    segment_id = _string(payload.get("segment_id"))
    text = _string(payload.get("text")) or _string(payload.get("rendered"))
    audio_offset_ms = _number(payload.get("audio_offset_ms"))
    duration_ms = _number(payload.get("duration_ms"))
    if (
        not segment_id
        or not text
        or audio_offset_ms is None
        or duration_ms is None
        or audio_offset_ms < 0
        or duration_ms <= 0
        or not math.isfinite(audio_offset_ms + duration_ms)
    ):
        return None

    audio_offset = audio_offset_ms / 1000
    duration = duration_ms / 1000
    source = _string(payload.get("timing_source"))
    if source != "alignment":
        return _fallback_timing(
            segment_id,
            text,
            audio_offset,
            duration,
            _fallback_reason(payload),
        )

    words = _validated_words(payload.get("words"), audio_offset_ms, duration_ms)
    if words is None or _normalized_tokens(text) != [
        _normalized_token(word.text) for word in words
    ]:
        return _fallback_timing(segment_id, text, audio_offset, duration, "invalid")

    return SpeechTiming(
        segment_id=segment_id,
        text=text,
        timing_source="alignment",
        audio_offset=audio_offset,
        duration=duration,
        fallback_reason=None,
        words=tuple(words),
    )


def _fallback_timing(
    segment_id: str,
    text: str,
    audio_offset: float,
    duration: float,
    reason: str,
) -> SpeechTiming:
    return SpeechTiming(
        segment_id=segment_id,
        text=text,
        timing_source="duration_fallback",
        audio_offset=audio_offset,
        duration=duration,
        fallback_reason=reason,
    )


def _validated_words(
    raw_words: Any,
    audio_offset_ms: float,
    duration_ms: float,
) -> list[SpeechTimingWord] | None:
    if not isinstance(raw_words, list) or not raw_words:
        return None

    segment_end_ms = audio_offset_ms + duration_ms
    previous_start_ms = audio_offset_ms
    previous_end_ms = audio_offset_ms
    words: list[SpeechTimingWord] = []
    for index, raw_word in enumerate(raw_words):
        if not isinstance(raw_word, dict):
            return None
        text = _string(raw_word.get("text"))
        start_ms = _number(raw_word.get("start_ms"))
        end_ms = _number(raw_word.get("end_ms"))
        if (
            not text
            or start_ms is None
            or end_ms is None
            or start_ms < audio_offset_ms
            or end_ms <= start_ms
            or end_ms > segment_end_ms
            or (
                index > 0
                and (start_ms < previous_start_ms or start_ms < previous_end_ms)
            )
        ):
            return None
        words.append(SpeechTimingWord(text, start_ms / 1000, end_ms / 1000))
        previous_start_ms = start_ms
        previous_end_ms = end_ms
    return words


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _fallback_reason(payload: dict[str, Any]) -> str:
    reason = _string(payload.get("fallback_reason"))
    return reason if reason in _FALLBACK_REASONS else ("invalid" if reason else "missing")


def _normalized_tokens(text: str) -> list[str]:
    return [_normalized_token(token) for token in text.split()]


def _normalized_token(token: str) -> str:
    return "".join(character.lower() for character in token if character.isalnum())


def _word_ranges(text: str) -> list[tuple[int, int, str]]:
    ranges: list[tuple[int, int, str]] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        start = index
        while index < len(text) and not text[index].isspace():
            index += 1
        ranges.append((start, index, _normalized_token(text[start:index])))
    return ranges


def _deduplicated_timings(timings: Iterable[SpeechTiming]) -> list[SpeechTiming]:
    latest_by_id: dict[str, SpeechTiming] = {}
    for timing in timings:
        latest_by_id[timing.segment_id] = timing
    return sorted(
        latest_by_id.values(),
        key=lambda timing: (timing.audio_offset, timing.segment_id),
    )


def visible_text(
    target: str,
    timings: Iterable[SpeechTiming],
    playback_position: float,
) -> str:
    """Return the target prefix explained by timing at this playback position."""
    if not target or not math.isfinite(playback_position):
        return ""
    target_words = _word_ranges(target)
    if not target_words:
        return ""

    target_cursor = 0
    visible_end: int | None = None
    for timing in _deduplicated_timings(timings):
        expected_words = _normalized_tokens(timing.text)
        if not expected_words or target_cursor >= len(target_words):
            continue
        if len(expected_words) > len(target_words) - target_cursor:
            continue

        mapping_start: int | None = None
        for candidate_start in range(
            target_cursor, len(target_words) - len(expected_words) + 1
        ):
            candidate = target_words[candidate_start : candidate_start + len(expected_words)]
            if [word[2] for word in candidate] == expected_words:
                mapping_start = candidate_start
                break
        if mapping_start is None:
            continue

        if playback_position < timing.audio_offset:
            break
        mapped_count = len(expected_words)
        if timing.uses_word_timing:
            visible_count = min(
                mapped_count,
                sum(word.start <= max(0, playback_position) for word in timing.words),
            )
        else:
            elapsed = playback_position - timing.audio_offset
            if elapsed <= 0:
                visible_count = 0
            else:
                progress = min(1.0, max(0.0, elapsed / timing.duration))
                visible_count = mapped_count if progress >= 1 else max(
                    1, math.ceil(progress * mapped_count)
                )

        if visible_count:
            visible_end = target_words[mapping_start + visible_count - 1][1]
            while visible_end < len(target) and target[visible_end].isspace():
                visible_end += 1

        target_cursor = mapping_start + mapped_count
        if playback_position < timing.end:
            break

    return target[:visible_end] if visible_end is not None else ""


def duration_visible_text(
    target: str,
    playback_position: float,
    audio_duration: float,
) -> str:
    """Return a word prefix paced across a complete audio duration."""
    if (
        not target
        or not math.isfinite(playback_position)
        or not math.isfinite(audio_duration)
        or audio_duration <= 0
        or playback_position <= 0
    ):
        return ""
    ranges = _word_ranges(target)
    if not ranges:
        return ""
    progress = min(1.0, max(0.0, playback_position / audio_duration))
    count = len(ranges) if progress >= 1 else max(1, math.ceil(progress * len(ranges)))
    end = ranges[count - 1][1]
    while end < len(target) and target[end].isspace():
        end += 1
    return target[:end]


def fallback_visible_text(
    target: str,
    elapsed: float,
    *,
    words_per_second: float = DEFAULT_FALLBACK_WORDS_PER_SECOND,
) -> str:
    """Reveal text at a conservative rate when word timing is unavailable.

    Duration-fallback records are published after their PCM. This estimate
    keeps the caption moving during the short window before that record
    arrives; once it does, callers can switch to the segment's real duration.
    """
    if (
        not target
        or not math.isfinite(elapsed)
        or not math.isfinite(words_per_second)
        or words_per_second <= 0
    ):
        return ""
    word_count = len(_word_ranges(target))
    if word_count == 0:
        return ""
    estimated_duration = word_count / words_per_second
    return duration_visible_text(target, elapsed, estimated_duration)


def longest_valid_prefix(target: str, candidates: list[str | None]) -> str | None:
    """Choose the longest candidate that remains a prefix of the target."""
    valid = [candidate for candidate in candidates if candidate and target.startswith(candidate)]
    return max(valid, key=len) if valid else None
