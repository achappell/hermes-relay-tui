# Accessibility Re-review — Hermes Home Assistant Platform

## Verdict

Accessibility sign-off is not ready. The current spines are materially stronger
than the prior review: they now state a child-readable vocabulary, Profile
visibility, volatile shared-device text, reduced-motion intent, and
reconnect-only recovery. Those are resolved as design requirements. They are
not yet resolved across the current WebAssembly, iPad, iOS, TUI, and appliance
paths.

No Critical finding is evidenced. The remaining High findings affect primary
conversation access, privacy, or recovery; they are not implementation polish.
This review changes only this file. DESIGN.md and EXPERIENCE.md were not
edited.

### Resolution by requested area

| Area | Resolution |
|---|---|
| Child-readable labels | Partially resolved: the vocabulary is committed, but runtime labels and comprehension evidence do not match it consistently. |
| State-language mapping | Not resolved. The UX model is broader than the shared display contract and current renderer. |
| Assistive technology/focus | Not resolved. iOS has useful labels, but focus order/return and live-update behavior are not implemented end to end. |
| iPad canvas DOM mirror | Not resolved. The active iPad path is a bitmap canvas with no semantic mirror. |
| Contrast pairs | Partially resolved: current design-token pairs pass; decorative/implementation pairs remain unverified. |
| Room-distance typography | Partially resolved: minima are specified, but the shared LVGL renderer still uses 14px defaults and has no room-distance evidence. |
| Reduced motion | Partially resolved: mock and parts of iOS comply; the active canvas/LVGL path does not consume the preference. |
| Quiet/night sound | Not resolved. Only a global earcon switch exists, and promised follow-up cues are not wired. |
| Shared-device history | Partially resolved. The privacy rule is explicit, but reconnect hydration still delivers the latest response snapshot. |
| Profile before capture | Partially resolved. The appliance publishes it at heard; iOS and the persistent TUI header do not show it. |
| Recovery/Retry | Partially resolved. The UX meaning is clear, but TUI /retry means replay and room/iPad has no recovery action or route. |
| Validation language | Not resolved. Existing tests cover state mechanics, not child comprehension, accessibility trees, or copy success criteria. |

## Critical

None observed.

## High

### H1 — The state-language contract is not executable across surfaces

**Status: Not resolved.**

EXPERIENCE.md:171-193 now provides a useful matrix, including Working,
Something went wrong, Unavailable, Complete, Stopped, and Response ready. The
shared display schema still exposes only nine states and no transcribing,
complete, stopped, or distinct audio-unavailable state
(shared/display/README.md:15-18; home_display/web/src/state/protocol.ts:1-13).

The runtime then renders protocol names directly: ui_display.c:109-117 calls
ui_display_state_name, whose values are raw idle, heard, thinking, error, and
disconnected (ui_snapshot.c:35-44). The appliance publishes Heard you, while
the matrix's child label is Heard, and its coordinator mapping has no complete
or transcribing state (home_display/appliance.py:92-108). iOS also exposes an
arbitrary failure message as VoiceState.failed's label
(../hermes-relay-ios/HermesRelayIOS/Models/SessionModels.swift:45-63).

A child can therefore receive technical vocabulary or lose the distinction
between still working, failed, and audio unavailable. Define the per-surface
derivation and one approved primary phrase for each state, then make the
display renderer, iOS, TUI, and tests consume it. Choose deliberately between
Heard and Heard you; do not leave that succession crisis to individual
adapters.

### H2 — The active iPad path has no accessible DOM mirror

**Status: Not resolved.**

EXPERIENCE.md:257-258 requires a semantic mirror, one announcement per state
transition, completed-response announcement, Profile, recovery, and
unavailable text. App.svelte:4,134-140 mounts only WasmCanvas; the active
surface exposes a canvas labelled only Hermes home display
(home_display/web/src/surfaces/WasmCanvas.svelte:37-46). The WebAssembly ABI
exports framebuffer, tick, pointer, and action functions, not semantic state
or accessible text (shared/display/README.md:101-116;
home_display/web/src/state/wasm.ts:196-205).

StateSurface.svelte contains a possible HTML alternative, but it is not
mounted, and its single aria-live region wraps changing response text
(home_display/web/src/surfaces/StateSurface.svelte:10-34,115-132), which
would announce deltas too aggressively if promoted unchanged. The canvas host
only installs pointer handlers and a perpetual animation-frame loop
(home_display/web/src/state/canvas.ts:47-86,149-175).

VoiceOver users on the iPad cannot discover the current state, Profile,
response, or recovery route. Mount a bridge-owned semantic mirror driven by
accepted snapshots, keep the canvas hidden from assistive technology, and
test the actual accessibility tree in Safari/Guided Access. State announcements
and response announcements need separate, rate-limited live regions.

### H3 — Assistive-technology and focus behavior is specified but not closed

**Status: Not resolved.**

The intended order and focus return are written down
(EXPERIENCE.md:257-259), but the iOS view has a FocusState only for the
composer (ContentView.swift:11,16-18,166-176). The active HUD header announces
Hermes Relay plus connection and duration, not the Profile
(AmbientHUD.swift:299-339), and no code returns focus to state/Profile after
connection recovery or setup. The live transcript is marked updatesFrequently
(RecentTranscriptRail.swift:607-616), contrary to the spine's announce each
state once, not every delta rule.

The prompt contract is also internally split: the UX says Room Display prompt
mirrors are not actionable, while the shared contract advertises
prompt.choose/prompt.dismiss (shared/display/README.md:42-45), the LVGL
surface creates touch buttons (ui_display.c:156-170), and the Svelte dialog
has no initial-focus, focus-trap, or focus-restore behavior
(PromptOverlay.svelte:70-90). Decide whether v1 prompts are mirrors or
actions, then implement the corresponding modal/focus contract. Verify
VoiceOver order, keyboard equivalents, focus return, and one-time state
announcements on every supported client.

### H4 — Room-distance typography is documented but violated by the shared renderer

**Status: Partially resolved.**

DESIGN.md:238-244 specifies 56px primary state, 24px Profile/response, 20px
recovery, and a 14px Puck status that must be tested at distance. The Night
Console mock's dominant state can meet that intent, while its utility labels
remain 9–13px (mockups/direction-night-console.html:37-45,68-77).

The actual LVGL display uses LV_FONT_DEFAULT as Montserrat 14
(shared/display/wasm/lv_conf.h:16-17), and both the state and response labels
use that default without setting the design sizes
(firmware/esp32-s3-touch-lcd-7/main/src/ui_display.c:138-152). The
2026-09-07 smoke evidence explicitly leaves physical and iPad-specific review
outside the slice (docs/testing/home-03-kiosk-display.md:44-51); the earlier
record says the two-metre review was not performed
(docs/testing/home-03-kiosk-display.md:60-62).

The minima close the prior requirement gap, but the shipped shared renderer
does not demonstrate them. Apply the minimums to the real 1024×600 target,
keep utility labels supplementary, and record a two-metre/low-light check plus
the Puck TFT check.

### H5 — Shared-display reconnect hydration still risks exposing volatile text

**Status: Partially resolved.**

The privacy rule is now explicit: shared conversation text is volatile and must
not be rehydrated after reconnect/restart (EXPERIENCE.md:165-169,199-206).
The implementation keeps the latest snapshot in DisplayStatePublisher and
immediately yields it to every new subscriber
(home_display/state.py:193-240); the server sends that snapshot on a new
WebSocket connection (home_display/server.py:301-335). The browser resets its
sequence on every socket open and accepts the hydrated snapshot
(home_display/web/src/state/channel.ts:89-96,172-190).

There is no evidence of deliberate browser history storage, and iOS/TUI Local
History is the documented exception. The unresolved case is a browser
reconnect while response_text contains partial or completed room text:
current transport behavior rehydrates it despite the UX purge rule. Define
whether active-turn hydration is an explicit exception; otherwise scrub
response_text before reconnect hydration. Test refresh, WebSocket reconnect,
server restart, Retry, and cross-room isolation with partial and completed
text.

### H6 — Profile visibility is correct on the appliance path, absent on client headers

**Status: Partially resolved.**

The appliance does publish the active Profile as account and emits heard before
capture (home_display/appliance.py:323-353,627-647), so that portion of the
requirement is resolved. The UX still requires Profile in the iOS/TUI header
before capture (EXPERIENCE.md:212-216,250-258).

The iOS conversation view passes no Profile into AmbientHUDView
(ContentView.swift:98-132); its header contains only Hermes Relay, connection,
and duration (AmbientHUD.swift:299-339). The Profile is visible in Settings,
not in the ordinary capture path (RelayConfigurationView.swift:103-150). The
TUI's persistent composition has only a generic Header and connection/voice
status (app.py:630-643,785-815); the Profile appears in a post-connect message
or explicit /status output (app.py:1016-1029,1973-1977).

Wrong-profile routing is a trust failure, not decorative metadata. Put the
selected Profile in the conversation header before the microphone can open on
iOS and TUI, retain it through completion, and fail closed when it is unknown
or unavailable.

### H7 — Retry has conflicting meanings and no room-display route

**Status: Partially resolved.**

The UX contract correctly says Retry is a Client action that reconnects only,
leaves the interrupted turn unresolved, and requires a fresh turn
(EXPERIENCE.md:232-237). iOS has a Retry button only for failed; ordinary
disconnected uses Connect (AmbientHUD.swift:316-320,504-529). The TUI command
named /retry does something else: its registry says “Retry the last prompt only
when it was never sent,” and its handler replays that prompt
(commands.py:78-84; app.py:2535-2559). Automatic reconnect exists, but the
user-facing hint says to retry later rather than exposing a reconnect action
(app.py:339-346,1041-1047).

Room/iPad surfaces have no Retry capability and no concrete route to a Client;
the canvas only reports a generic error element when its host fails
(WasmCanvas.svelte:37-46). Reserve Retry for reconnect, rename or separate the
safe unsent-prompt replay command, and expose the unresolved-turn warning plus
fresh-turn instruction in the accessible client surface. Give a room-safe,
non-actionable message an explicit destination.

## Medium

### M1 — Contrast-token repair is resolved; rendered-pair coverage is not

**Status: Partially resolved.**

Recalculation against the current DESIGN.md:20-35 tokens gives:

- ink-primary on surface-console: **16.43:1**.
- ink-secondary on surface-panel: **10.07:1**.
- accent-identity-on on accent-identity: **6.39:1**.
- border-emphasis on surface-panel: **5.18:1** for a non-text boundary.
- status-unavailable on surface-panel: **7.66:1**.

The prior review's 2.72:1 identity and 2.01:1 emphasis figures do not
reproduce against the current tokens; those specific H3 defects are resolved.
border-subtle remains only **1.52:1** against surface-console and **1.57:1**
against surface-panel, so it must remain decorative and never carry grouping,
focus, or state. The mock's #718097 bracket is **4.47:1** on #101725;
acceptable only as decorative punctuation, not semantic text
(mockups/direction-night-console.html:51-54).

The active Web CSS and LVGL renderer use separate palettes
(home_display/web/src/styles.css:1-14; ui_display.c:44-54), with no
automated contrast check in the current smoke evidence. Test actual text,
focus, borders, error, prompt, and ambient-media overlays at rendered sizes.

### M2 — Reduced-motion intent is not carried through the active canvas path

**Status: Partially resolved.**

The spine and mock explicitly require a static frame
(EXPERIENCE.md:246-253; direction-night-console.html:94-97), and iOS pauses
the ambient visualizer when accessibilityReduceMotion is set
(AmbientHUD.swift:379-406). However, the active browser path runs LVGL on
requestAnimationFrame without reading prefers-reduced-motion
(canvas.ts:61-86,138-159). The only Web CSS reduction rule disables the
working dot and smooth scrolling in the unused StateSurface path
(styles.css:258-269; App.svelte:134-140). VoiceStatusView also applies an
unconditional state animation (VoiceStatusView.swift:20-23).

Pass the preference to the shared renderer or provide a static DOM/canvas
mode; disable visualizer loops, connection motion, smooth scroll, and reveal
effects while retaining readable text and any separately controlled sound
preference. Test each active state, not only the mock.

### M3 — Quiet/night sound behavior and promised follow-up cues remain open

**Status: Not resolved.**

EXPERIENCE.md:252,260 permits quiet/night suppression and forbids unsolicited
Departure/Disconnected audio, but does not name the preference, default,
volume policy, or cue timing. The implementation has only two generated
earcons—wake and capture-done (earcons.py:27-50)—and one global
--no-earcons switch (config.py:1207-1213). The follow-up path enters a new
capture without an opening-cue hook and times out through _finish without a
closing-cue hook (handsfree.py:226-240,284-300). Current manual checks cover
the wake/capture tones and global off switch, not night behavior or follow-up
open/close (docs/testing/voice-08-home-10-voice-10-manual-plan.md:144-186).

Document a cue table, quiet/night ownership, and sound-off behavior. Add
follow-up-open, follow-up-close, unavailable-identity, and audio-unavailable
cases; visual state must remain sufficient when every cue is suppressed.

### M4 — “Child-readable” and recovery copy have no comprehension criteria

**Status: Not resolved.**

The spine asks for child validation and limits the pilot to English
(EXPERIENCE.md:250-261), but the available validation evidence checks state
transitions, ear-only tones, and no-earcon operation—not whether a child
understands Working, Unavailable, Stopped, or reconnect-only Retry
(docs/testing/voice-08-home-10-voice-10-manual-plan.md:144-186;
docs/testing/home-03-kiosk-display.md:44-62). It also has no accessibility-tree,
keyboard/focus, contrast, reduced-motion, or quiet/night acceptance run.

Define a copy test with the primary labels and recovery message shown without
color or sound. Ask representative child users what the device is doing and
what they would do next; set a pass threshold, record exact misunderstandings,
and repeat at room distance. Pair that with VoiceOver/keyboard-tree checks and
the same test under reduced motion and sound-off. Do not treat font size or a
designer's assertion as comprehension evidence.

## Low

### L1 — English-only and dense secondary chrome need a later language pass

**Status: Not resolved; low for the English pilot.**

The English pilot boundary is explicit (EXPERIENCE.md:261), but tracked
uppercase labels, short status strings, and the 9–13px mock chrome
(direction-night-console.html:37-45,77) have no localization width,
line-wrapping, or child-comprehension review. This does not block the English
pilot while those strings remain supplementary. Before localization, recheck
translated state words, Profile names, recovery text, cue timing, and the
smallest Puck/display surfaces.

## Confirmed closures from this re-review

- The current design-token identity and emphasis contrast pairs pass; the
  prior arithmetic finding is closed.
- The UX contract now explicitly makes readable text authoritative over color,
  motion, and sound, and explicitly keeps Departure Cards visual-only.
- The appliance path publishes Profile identity before capture and clears its
  partial reply on a transport failure (home_display/appliance.py:1018-1029).
- iOS voice controls have useful accessible labels and hints
  (VoiceControl.swift:105-119), and the iOS ambient visualizer has a reduced
  motion branch. These are foundations, not closure of the cross-surface
  requirements above.
