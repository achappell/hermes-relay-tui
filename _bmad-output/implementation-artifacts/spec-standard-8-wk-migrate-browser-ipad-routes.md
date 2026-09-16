---
id: STANDARD-8-WK
title: Migrate the shared W/K browser and iPad route to Standard Hermes
type: feature
created: 2026-09-15
status: done
github_issue: https://github.com/achappell/hermes-relay-tui/issues/185
baseline_commit: 0116a6566dfe3860f6d52c658437116a7a0992b5
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/surface-coverage-matrix.md'
  - '{project-root}/docs/bmad-upstream.md'
warnings:
  - 'The public Home browser route is not live in the current Home revision; fake bridge evidence is the available integration evidence.'
deferred:
  - summary: 'Run the approved Home-route and physical Safari/iPad W/K acceptance gate after HOME-NW-01, HOME-NW-02, and HOME-NW-03 are delivered.'
    evidence: 'The Home bridge contract is planned and this checkout has no approved public route or paired production credential.'
    location: 'home_display/appliance.py; docs/ops-web-deployment.md'
    severity: high
---

# Standard-8 — W/K migration

## Scope

Move the single shared web/iPad deployment surface behind Home and the pinned
Standard Hermes boundary. iPad is a deployment target, not another surface.

## Acceptance

- Browser bootstrap uses an approved route and endpoint credential without
  putting secrets in URLs or browser history.
- Text, response audio, prompts, interruption, reconnect, and explicit timing
  behavior match Standard semantics.
- Concurrent W/K sessions remain isolated, and passive display mode creates no
  second turn.
- Physical Safari/iPad, safe-channel, audio, touch, kiosk, and concurrent
  session validation are recorded.

## Dependencies

HOME-NW-01, HOME-NW-02, HOME-NW-03, and the existing W/K session-isolation
foundation.

## Intent

The browser and iPad deployment must use the same Home-owned Standard Hermes
boundary. The appliance remains the trusted server-side adapter: it holds the
Device credential and opaque conversation handle, while the browser receives
only the existing same-origin display state and audio channel. The current
direct-profile browser transport remains an explicit rollback path until the
approved Home route and physical evidence exist.

## Boundaries & Constraints

**Always:** require the exact secure `wss://.../api/v1/bridge/ws` route; send
`Authorization: Device <credential>` only from the appliance; bind every Home
request, event, audio frame, and prompt response to the configured opaque
conversation handle and active turn; keep one Home reader per browser session;
stream Standard text and signed 16-bit little-endian PCM; use
`prompt.respond` for supported choice/clarify controls; preserve explicit
`timing: absent`; and reconnect without replay after uncertain delivery.

**Never:** put a Device credential or bearer in a URL, browser payload,
snapshot, or log; fall back from Home to a direct bearer session; send a local
Profile ID across the Home bridge; treat an interrupt acknowledgement as turn
completion; invent arrival timing; or claim physical Safari/iPad, kiosk,
secure-channel, audio, touch, or concurrent live evidence from fakes.

## I/O & Edge-Case Matrix

| Scenario | Input / state | Expected behavior | Failure handling |
| --- | --- | --- | --- |
| CONNECT | Home mode with route, Device credential, and opaque handle | Open the pinned route and accept only an approved ready result | Missing pairing, wrong URL, unavailable route, or malformed readiness fails closed |
| TEXT | Browser text while the Home session is ready | Send one `prompt.submit`; consume only the returned active turn | Known rejection stays non-delivery; transport failure is uncertain and never replayed |
| AUDIO | Home PCM sidecar frames | Validate handle, turn, mono signed-16 little-endian metadata and sample boundaries; forward in order | Invalid, foreign, or unavailable audio is typed and cannot complete another turn |
| PROMPT | Choice or clarify event with prompt/correlation identity | Render one browser prompt and answer through `prompt.respond` | Stale, mismatched, secret, or sudo actions are rejected or reported unavailable |
| INTERRUPT | Active Home turn and advertised capability | Send `session.interrupt` and wait for the matching terminal event | An acknowledgement alone never ends the turn |
| RECONNECT | Socket loss after a submit or response | Mark delivery uncertain and use `conversation.reconnect` | Require a fresh browser action; never resend the old text or response |
| BROWSER | Multiple state sockets | Give each socket a private session, publisher, audio stream, and turn lock | A foreign socket/event cannot alter this browser's state |
| PASSIVE | Display-only browser with no voice action | Render snapshots only; create no browser turn | No direct Hermes/Home prompt is created by display observation |
| ROLLBACK | `legacy` transport selected | Keep the existing direct-profile browser path | No transport changes during an active or uncertain turn |

## Code Map

- `puck_bridge/home_session.py` — browser-specialized Home session, structured
  prompt response, timing capability, Standard event/audio normalization,
  interrupt, reconnect, and no-replay state.
- `home_display/appliance.py` — explicit `legacy|home` browser transport,
  private route/pairing resolution, connection-scoped Home browser sessions,
  local wake gates, prompt handling, and fail-closed startup.
- `config.py` — Home transport config and private Device/handle resolution;
  Home mode does not resolve legacy bearer profiles.
- `home_display/state.py` and `home_display/web/src/state/protocol.ts` — the
  explicit `timing: absent` capability contract for Python and browser clients.
- `tests/test_puck_home_session.py`, `tests/test_home_appliance.py`,
  `tests/test_household_profiles.py`, `tests/test_home_display_state.py`, and
  `home_display/web/src/state/protocol.test.ts` — fake protocol, security,
  isolation, prompt, timing, parser, and fail-closed coverage.
- `README.md`, `config.example.yaml`, and `docs/ops-web-deployment.md` — the
  opt-in operator path, private input rules, rollback, and live evidence gate.

## Tasks & Acceptance

- [x] Add a browser Home session on the existing adapter seam with exact route,
  handle, turn, correlation, prompt-response, interrupt, reconnect, and
  no-replay validation.
- [x] Add explicit Home browser transport selection and private pairing
  resolution; keep `legacy` as the default and fail closed without Home inputs.
- [x] Keep concurrent browser contexts isolated and preserve passive display
  behavior without creating a second turn.
- [x] Carry the Home timing contract as `absent` through the display snapshot
  parser without changing legacy snapshots.
- [x] Add focused fake tests and document the browser/iPad route, credentials,
  prompt limits, rollback, and evidence boundary.
- [ ] **Deferred external gate:** after HOME-NW-01/02/03, record physical
  Safari/iPad secure-channel, audio, touch, kiosk, concurrent-session, and
  approved Home-route text/response/interrupt/reconnect evidence.

## Verification Record

- Clean baseline from `0116a6566dfe3860f6d52c658437116a7a0992b5` — **1,371 passed**, 1 skipped, 6 dependency warnings.
- Focused fake Home/browser/timing/profile checks — **14 passed**; the stale
  action, correlated prompt response, parser isolation, and composed browser
  turn paths are covered.
- Full Python suite after implementation — **1,383 passed**, 1 skipped, 6
  dependency warnings.
- Browser suite — **209 passed**; `svelte-check` — **0 errors, 0 warnings**;
  production Vite build — passed.
- Live Home route, production credential, and physical W/K evidence —
  **deferred**; no approved endpoint is available in this checkout.
- Post-review repair verification — focused Home/session suite **75 passed**;
  full Python suite **1,384 passed**, 1 skipped, 6 dependency warnings; browser
  suite **209 passed**; `svelte-check` **0 errors, 0 warnings**; production
  Vite build passed.

## Review Triage Log

The blind-hunter and verification-gap reviewers independently reproduced the
two integration defects below. Findings are retained here even when they were
rejected or deferred; duplicate reports share one root-cause row.

| Reviewer finding | Disposition | Evidence / decision |
| --- | --- | --- |
| Blind + verification: Home terminal completion was swallowed before the browser's `turn_end` branch. | patch | `HomeBrowserSession` now emits the browser terminal event after validated Home exhaustion; the adapter and appliance-path tests cover it. |
| Blind + verification: Home prompt events use `prompt_kind`, while the appliance read `kind`. | patch | The classifier accepts the normalized Home field and the focused classifier test covers choice and clarify routing. |
| Blind: choice/approval labels and IDs were replaced with fixed `yes`/`no` values. | patch | Home option IDs and labels are preserved; malformed or empty Home choices fail closed. The adapter rejects an option ID not present in the pending prompt. |
| Blind: prompt resolution matched only `prompt_id`, not correlation identity. | patch | Home browser action IDs use the required correlation identity, and resolution matching accepts both prompt and correlation IDs. |
| Blind: delayed actions could collide with a reused legacy prompt ID. | defer | The Home path now uses the per-request correlation identity; legacy prompt IDs remain an existing gateway boundary and no live evidence establishes a different generation contract. |
| Blind: prompt text, fields, and option lists were unbounded before display. | patch | The browser classifier bounds prompt text, IDs, labels, and option count and rejects malformed Home data before publication; the bridge frame itself remains size-bounded. |
| Blind: secret/sudo prompts could leave the browser waiting when interruption was unavailable. | patch | Unsupported prompts now fail closed and terminate/reconnect when no confirmed interrupt path exists; an interrupt acknowledgement still does not complete the turn. |
| Blind: a Home transport failure closed the browser without attempting `conversation.reconnect`. | patch | A Home browser context reconnects the same adapter after an uncertain failure, preserves the browser socket when possible, and requires a fresh turn; it never replays the old prompt. |
| Blind: known `prompt.submit` rejection was treated as transport loss. | patch | The appliance keeps the verified Home connection and reports known non-delivery as a recoverable error. |
| Blind + verification: Home parser startup resolved legacy bearer profiles before Home mode was known. | patch | The Home parser detects transport before building the base parser and disables relay-token resolution; a malformed legacy token source is covered by a parser-level test. |
| Blind: `browser_transport=home` without browser voice reached the local recorder path. | patch | Appliance build now rejects that combination before opening or binding local audio. |
| Blind: Home structured-prompt capability was unconditional. | defer | The current Home readiness contract has no prompt-capability vocabulary, while STD-8 requires choice/clarify support from the browser adapter. Revisit when HOME-NW-01/02 publishes negotiated prompt capabilities. |
| Blind: pending Home responses did not validate selected option IDs. | patch | Pending option IDs are retained and checked before `prompt.respond`; invalid choices do not write a frame. |
| Blind: raw binary frames have no independent turn identity and could be late. | defer | The pinned bridge contract supplies turn identity on the JSON audio envelope but not on raw PCM. The adapter rejects foreign JSON audio envelopes; eliminating late raw-frame ambiguity requires a Home transport contract change. |
| Blind: conflicting correlation IDs were silently accepted. | patch | The adapter now rejects conflicting non-empty correlation fields as a protocol error. |
| Blind: unsupported prompt debug logging included the complete event. | patch | Logging now records only structural kind and identifier fields, never prompt text or option payloads. |
| Blind: composed Home-to-appliance coverage was missing. | patch | Added parser, classifier, Home terminal, option validation, and composed Home browser-turn tests. Physical Safari/iPad and approved-route evidence remain the deferred external gate. |

The replacement edge-case reviewer was interrupted before returning a report;
the targeted edge scan above and the two completed independent reports are the
available review evidence for this local pass.

The post-repair blind, edge-case, and verification-gap reviewers returned no
additional implementation findings. They reconfirmed the two deferred contract
items (negotiated prompt capability and raw PCM turn identity) and the external
Home/Safari/iPad evidence gate. The rebuilt `home_display/static/index.html`
references the intentionally replaced generated bundle
`home_display/static/assets/index-_sr_QcXU.js`.

### Review Findings

The four delegated review passes timed out without returning reports. The
findings below are from direct local review against the adapter, appliance, and
current Home bridge contract; the repaired code was then checked by the
focused and full verification gates below.

- [x] [Review][Patch] A malformed structured prompt can inherit the previous event's correlation ID [puck_bridge/home_session.py:891-919,1224-1267,1738-1797] — fixed by rejecting supported structured prompts without a fresh correlation identity, removing the pending-prompt fallback to prior state, and adding a two-prompt regression test.
- [x] [Review][Patch] Choice responses can bypass the pending option list through `value` [puck_bridge/home_session.py:1077-1089,1488-1505] — fixed by requiring a non-empty pending option ID for choice/approval/confirm prompts, rejecting arbitrary `value` choices, and adding regression coverage that no `prompt.respond` frame is written.
- [x] [Review][Defer] Home browser contexts reuse one opaque handle across independent sockets [home_display/appliance.py:1761-1781] — deferred: the Home route adapter is not present in this checkout, so it is not yet defined whether multiple bindings for this configured handle may safely resume one durable Standard Session while preserving the story's concurrent-session isolation requirement. Resolve with the Home route contract and an approved overlapping two-tab evidence run.
- [x] [Review][Defer] Home structured-prompt support is advertised without negotiated capability [puck_bridge/home_session.py:1824-1832] — deferred: the current Home readiness contract has no prompt-capability vocabulary. Revisit when HOME-NW-01/02 publishes negotiated prompt capabilities; this item is already tracked in the prior triage log.
- [x] [Review][Defer] Raw Home PCM has no independent turn identity [puck_bridge/home_session.py:819-833] — deferred: the pinned contract carries turn identity on the JSON audio envelope but not on raw PCM, so eliminating late-frame ambiguity requires a Home transport contract change; this item is already tracked in the prior triage log.
- [x] [Review][Defer] The approved Home-route and physical Safari/iPad acceptance gate remains unverified [home_display/appliance.py; docs/ops-web-deployment.md] — deferred: no approved public route, paired production credential, or physical W/K environment is available in this checkout. Fake bridge evidence cannot prove secure-channel, audio, touch, kiosk, concurrency, or live reconnect behavior.

#### Rejected

- [Review][Rejected][low] `HomeBrowserSession` appends `turn_end` after an exhausted base stream even when the base stream yielded an error or interruption — the shipped appliance returns immediately for those terminal error kinds and closes the stream, so no false completion reaches the current caller; a generic full-drain consumer is outside this slice.
- [Review][Rejected][low] A delayed browser `Blob` could resolve after reconnect and feed stale PCM — the browser channel explicitly requests `arraybuffer` delivery, making Blob the non-standard fallback path; adding complexity for that edge is not worth fixing before the Home audio contract is settled.
