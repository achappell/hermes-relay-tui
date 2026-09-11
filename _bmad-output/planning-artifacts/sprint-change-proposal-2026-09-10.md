---
title: "Sprint Change Proposal — W/K browser transcript and hands-free recovery"
type: sprint-change-proposal
created: 2026-09-10
status: approved
route: incremental
change_scope: moderate
trigger: "Live W/K browser smoke exposed missing user transcription, undefined response retention, and Samsung Bespoke post-playback hands-free failure."
---

# Sprint Change Proposal — W/K browser transcript and hands-free recovery

## 1. Issue Summary

### Trigger and context

The findings were made during live W/K browser validation after the browser
audio path was repaired. Chrome completed a real Hermes turn and Amanda's
subjective audio check was good. A Samsung Bespoke smart-fridge browser then
completed its first voice turn, but hands-free failed when recognition needed
to resume after the response.

The same validation also exposed two presentation gaps:

1. The W/K surface sends the captured user utterance to Hermes but does not
   show the user's transcription.
2. The W/K surface has no explicit policy for how long a completed response
   remains readable. It currently retains response text in the idle snapshot,
   but has no bounded timeout and no browser-local “clear when the next capture
   begins” rule.

### Evidence

- Live Chrome/Hermes smoke delivered one `audio_start`, one `audio_end`, eight
  ordered PCM chunks, and 51,712 bytes; the browser rendered the expected
  response.
- The web suite passes 165 tests; `npm run check` reports zero diagnostics;
  the production build succeeds; the Python suite passes 927 tests.
- `home_display/state.py` exposes `response_text` but no user-transcript field.
- `BrowserVoiceController` sends final recognition text, but exposes no
  transcript presentation callback.
- `StateSurface.svelte` displays `response_text` only for `speaking` and
  `idle`; the appliance clears it when a new browser turn starts and retains
  it after successful completion, but no bounded retention timer exists.
- `BrowserHandsFreeController` already retries the Safari silent-hang variant.
  Other post-playback recognition errors are currently collapsed into
  “Microphone or speech recognition is unavailable,” and the browser error
  code is not retained for diagnosis.

The exact Samsung browser `SpeechRecognitionErrorEvent.error` value was not
captured. That is an implementation-validation item, not evidence that the
fridge lacks microphone or speech-recognition support: its first turn proves
that the initial path worked.

## 2. Impact Analysis

### Epic impact

- Epic 1 remains achievable. The Hermes/audio transport repair is not being
  rolled back.
- Epic 1 surface story `WK-1` needs an explicit post-playback hands-free
  recovery invariant across supported browser deployments.
- Epic 2 surface story `2-WK-2` is the existing owner for W/K active capture,
  transcription, response, and phase presentation. It needs the user-
  transcription and response-retention acceptance details.
- No new epic, epic removal, or epic resequencing is required.

### Story impact

The two approved incremental proposals are recorded in Section 4. They refine
existing surface stories; they do not create a competing backlog or claim
that iPad is a separate surface.

### Artifact conflict and impact

| Artifact | Finding | Proposed treatment |
|---|---|---|
| PRD | FR2, FR4, UJ-1, and UX-DR9 already require live transcription and a visible completed answer. No contradiction exists; the exact W/K timeout is underspecified. | No PRD edit. Carry the browser-specific timing and trigger into `2-WK-2`. |
| Architecture | AD-2 makes presentation state surface-local, and AD-6 keeps the browser as an adapter. A browser-local transcript/retention state does not require a shared snapshot field or wire change. | No architecture edit. If a future passive-room requirement needs the user's transcript in `DisplaySnapshot`, run the separate AD-10 schema/fixture review first. |
| UX Design / Experience | The shared UX already distinguishes live versus completed transcript treatment and requires completed response visibility. The new timing is specific to the W/K browser surface. | No global UX edit. The W/K story spec will define the visible user-text treatment, 60-second default, next-capture clear, and safe terminal-state behavior. |
| Testing and documentation | Browser unit/App tests do not cover a successful first turn followed by vendor-specific post-playback recognition failure, nor the requested retention policy. | Add focused fake-recognition/timer coverage, safe error classification, and Samsung Bespoke manual smoke evidence. |
| Shared display schema | No change is needed for the active W/K surface; its browser controller already knows recognition text. | Do not expand schema 1 for this slice. |

### Technical impact

The implementation will remain in the W/K browser adapter:

- add interim/final transcript presentation callbacks or equivalent local
  controller state;
- render user text distinctly from Hermes response text;
- clear the previous response at the beginning of any new push-to-talk or
  hands-free capture;
- hide completed response text after a 60-second default retention window;
- classify and safely retain post-playback recognition error categories for
  bounded retry and honest user feedback without exposing raw audio, prompts,
  tokens, or unnecessary browser internals;
- preserve the existing no-replay, one-turn, audio lifecycle, and reconnect
  invariants.

No server endpoint, Hermes wire frame, credential flow, transcript archive, or
shared database is introduced.

## 3. Recommended Approach

### Options considered

| Option | Assessment |
|---|---|
| Direct adjustment of existing W/K stories | **Viable.** Medium effort, medium browser-compatibility risk, low timeline impact. Uses the existing local state boundary and focused tests. |
| Roll back the audio/browser repair | **Not viable.** The live turn now delivers coherent PCM and the reported failures are presentation and post-playback recognition-lifecycle issues. Rollback would discard verified progress without addressing either finding. |
| Reopen PRD/MVP scope | **Not viable.** The product goals and MVP remain intact; the findings clarify delivery acceptance rather than reduce or redefine the product. |

### Recommendation

Use a direct adjustment with two existing surface owners:

1. Keep `WK-1` responsible for the browser doorway's complete voice lifecycle,
   including post-playback hands-free recovery across supported browsers.
2. Refine `2-WK-2` as the browser active-turn presentation story for user
   transcription and bounded response retention.
3. Implement the follow-on work in a new clean W/K feature worktree after
   this proposal is approved. Do not mix it into the current uncommitted
   audio-repair slice.
4. Treat Samsung Bespoke validation as a required manual compatibility gate;
   do not infer support or failure from the generic message alone.

The recommended default response-retention period is 60 seconds. A new
capture clears the previous response immediately, even if the new capture is
cancelled or produces no usable text. Terminal error/disconnect states clear
conversation presentation according to the existing safety rules.

### Effort, risk, and timeline

- Effort: medium — browser controller/UI changes, focused tests, build checks,
  and a physical fridge smoke.
- Risk: medium — browser-native SpeechRecognition implementations differ, and
  the Samsung error code still needs observation.
- Timeline impact: a separate follow-on slice; no rollback or PRD review.

## 4. Detailed Change Proposals

### Proposal A — `WK-1` post-playback hands-free recovery

**Incremental decision:** Approved by Amanda.

**Section:** Surface-specific scope and acceptance.

**OLD**

> One shared W/K browser voice-plus-display surface for authorized capture,
> honest phases, streamed/completed response text, response audio, and
> delivery/error state.

**NEW**

> One shared W/K browser voice-plus-display surface for authorized capture,
> honest phases, streamed/completed response text, response audio,
> delivery/error state, and bounded post-playback hands-free recovery across
> supported browsers.

**Acceptance addition**

> Given a successful W/K voice turn and completed response playback, when the
> browser resumes hands-free recognition, then it accepts the configured
> follow-up within the bounded window or exits with a specific, honest
> recoverable error; transient restart failures are retried within the window,
> and no duplicate turn is submitted.

**Rationale:** The fridge's first turn establishes that initial capture works;
the failure is at the post-playback lifecycle boundary. The story must cover
that boundary without claiming every vendor's implementation is identical.

### Proposal B — `2-WK-2` user transcription and response retention

**Incremental decision:** Approved by Amanda.

**Section:** Surface-specific scope and acceptance criteria.

**OLD**

> Render active capture, room-local Transcription, response, and phase state
> in the browser surface.

**NEW**

> Render active capture with live and final user Transcription, streamed and
> completed Hermes response text, explicit phase/audio state, and bounded
> post-turn response retention in the browser surface.

**Acceptance additions**

- During browser capture, interim and final recognition text is visible as the
  user's transcription. The final utterance remains visible through
  submission and is transient; it is cleared on the next capture or terminal
  failure and is never archived.
- After a successful response, the completed Hermes response remains visible
  after playback while idle until the next capture begins or 60 seconds elapse,
  whichever comes first.
- Starting a new push-to-talk or hands-free capture clears the previous
  response immediately.
- The browser does not claim `Speaking` when audio is unavailable, and
  recovery/error states clear stale conversation text safely.

**Rationale:** Epic 2 already owns W/K active-turn presentation. Browser-local
state satisfies the existing requirements without expanding the shared
snapshot contract or introducing transcript persistence.

### Non-edits to PRD, architecture, and global UX

No changes to the PRD, architecture spine, shared display schema, or global UX
documents are proposed in this correction. Their existing rules remain the
constraints for the follow-on story.

## 5. Implementation Handoff

### Scope classification

**Moderate.** The code change is a bounded browser-adapter slice, but the work
requires formal refinement of two surface stories, a new owning story/spec
record, tracker synchronization, and a vendor-browser manual gate.

### Handoff recipients

- **Product Owner / BMad planner:** finalize the two approved story refinements,
  create or update the owning W/K story specification, and synchronize local
  `epics.md`, `sprint-status.yaml`, and the evidence index. GitHub Project #3
  remains paused and is not part of this handoff.
- **Developer:** implement the Svelte/browser controller changes in a clean
  follow-on worktree; add focused tests before the full suite; preserve the
  current audio and no-replay behavior.
- **Amanda / manual validation:** run the real Samsung Bespoke smoke after the
  bundle is served, capture the safe recognition error category if recovery
  still fails, and verify a successful first turn followed by hands-free
  follow-up, response retention, and next-capture clearing.

### Success criteria

1. The W/K surface shows interim/final user transcription during capture and
   does not persist it as a transcript archive.
2. A completed response remains readable after playback until the next capture
   or 60 seconds, whichever comes first.
3. Hands-free recovery after the first response either resumes on the Samsung
   Bespoke browser or reports a precise bounded failure after its retry budget;
   it never leaves misleading phantom listening or submits a duplicate turn.
4. Existing Chrome and iPad/Safari follow-up behavior remains green in focused
   tests and manual evidence.
5. Browser checks, production build, full Python suite, and the physical fridge
   smoke are recorded in the owning story artifact.

### Checklist record

- [x] 1.1 Triggering story identified: `WK-1`, with presentation routed to
  `2-WK-2`.
- [x] 1.2 Core problem categorized as implementation/acceptance gaps revealed
  by stakeholder and live-platform feedback.
- [x] 1.3 Evidence recorded; exact Samsung browser error code remains an
  explicit validation action.
- [x] 2.1–2.5 Epic impact assessed: no new epic, rollback, or resequencing.
- [x] 3.1–3.4 PRD, architecture, UX, testing, and documentation impact
  assessed.
- [x] 4.1–4.4 Direct adjustment selected; rollback and MVP review rejected.
- [x] 5.1–5.5 Issue, impact, recommendation, MVP impact, and handoff recorded.
- [x] 6.1 Checklist is complete apart from final approval and implementation
  routing.
- [x] 6.2 Proposal reviewed for consistency and bounded scope.
- [x] 6.3 Final approval of this complete proposal recorded from Amanda on
  2026-09-10.
- [x] 6.4 Tracker/story artifact updates completed after approval.
- [x] 6.5 Follow-on implementation worktree created; Samsung manual handoff
  remains an implementation validation gate.

## Approval

This proposal contains the two individually approved edit proposals above and
was approved as a complete Sprint Change Proposal by Amanda on 2026-09-10.
The owning story artifacts, surface/tracker evidence, and clean follow-on
implementation slice are recorded in the post-approval handoff.

## Post-approval handoff

- `spec-1-wk-1-one-shared-w-k-browser-voice-plus-display-surface-for-author.md`
  records the `WK-1` recovery slice and is `ready-for-dev`.
- `spec-2-wk-2-render-active-capture-room-local-transcription-response-and.md`
  records the `2-WK-2` browser presentation slice and is `ready-for-dev`.
- `sprint-status.yaml` was regenerated from `epics.md` after those artifacts
  were created; the two surface stories were promoted from `backlog` to
  `ready-for-dev`.
- The BMad sprint-planning readiness gate passed; the generator reported no
  parser warnings, illegal statuses, or dropped orphan entries.
- The clean follow-on implementation worktree is
  `~/Development/hermes-relay-tui/.worktrees/wk-browser-transcript-recovery`
  on branch `fix/wk-browser-transcript-recovery`, created from the current
  repository tip without the uncommitted audio-repair slice.
- The two approved findings were removed from `docs/friction-log.md`; the
  formal BMad proposal and story artifacts are now authoritative.
