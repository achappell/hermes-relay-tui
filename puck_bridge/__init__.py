"""Standalone host-side bridge for the Puck's post-wake audio upload.

Spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`.

This package is deliberately not imported by `app.py` or
`home_display/appliance.py` -- it is its own process (see the spec's
Boundaries & Constraints), so this test harness cannot regress either
existing front end. It accepts one bounded, VAD-gated chunked audio upload
per wake event from the Puck (`receiver.py`), transcribes it locally with
the existing `voice.py:transcribe()` (unchanged), and drives exactly one
real Hermes turn through a directly-constructed
`handsfree.HandsFreeCoordinator` against `session.py`'s `SessionProtocol`
(`turn.py`), playing the response on this host machine's own speakers.
"""

from __future__ import annotations

__all__ = ["receiver", "turn", "server"]
