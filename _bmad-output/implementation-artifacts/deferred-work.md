# Deferred work

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md`
  summary: Harden the pre-existing reSpeaker diagnostic capture before it is enabled in a normal hardware build.
  evidence: The current dirty firmware configuration automatically captures four seconds of household PCM, emits it through serial logs, captures pre-processed microphone bytes rather than the wake model input, and shares capture state across the audio callback and interval task without synchronization. This work predates Story 1.3 and is outside its frozen intent; disable or make it explicitly opt-in before shipping.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md`
  summary: Add repeatable host and target verification for the pre-existing vendored reSpeaker microphone/DSP path.
  evidence: The local firmware component hard-codes a stereo 32-bit, 48 kHz FIR/decimation path while its schema exposes broader formats, uses unchecked signed byte shifts, leaves no coefficient generator or DSP fixture, and has no repository build or output test. The component and diagnostics were already dirty before this story and are not part of the TUI follow-up slice.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md`
  summary: Audit pre-existing reSpeaker lifecycle and audio-output error handling before relying on the vendored component in production.
  evidence: The dirty firmware tree leaves some configuration fields uninitialized or effectively dead and does not consistently handle I2S callback registration, channel-enable, preload, and partial-write failures. These findings concern the pre-existing hardware work, not the TUI adapter changed by this story.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md`
  summary: Reconcile generated BMad indexes and the older on-device wake-word story's status and provenance.
  evidence: The dirty generated index omits the existing firmware story, that story remains marked done despite its own unresolved detection notes, and its local-vendor documentation needs a single authoritative provenance/license record. This is historical firmware/planning reconciliation outside Story 1.3.

- source_spec: `_bmad-output/implementation-artifacts/spec-web-epic-1-reliable-conversation.md`
  summary: Add server-side validation for browser actions against the currently published prompt and advertised capability.
  evidence: `DisplayServer` currently treats `/action` as a same-origin transport callback and does not inspect the publisher's current prompt; the restored App validates actions through `DisplayBridge`, but a direct request can still reach the callback without that reducer gate. Implementing this safely requires a shared server-side action authority and is pre-existing transport behavior outside this DOM restoration.

- source_spec: `_bmad-output/implementation-artifacts/spec-web-epic-1-reliable-conversation.md`
  summary: Run the physical Safari/iPad HTTPS/WSS, permission, audio, and direct-touch gate for the restored DOM kiosk.
  evidence: The local fake-state and automated browser checks pass, but no physical iPad/Safari session was available in this worktree to verify Guided Access, secure state-channel hydration, microphone permission, audio playback, and touch-button operation on the supported device.
