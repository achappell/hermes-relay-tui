# Task 4 report

Commit: `cd7b631f2ca258b7cfa24af3cdf80f7728f97d5e` (`feat: add home display state surfaces`)

Files committed:

- `home_display/web/src/App.svelte`, `src/main.ts`, and `src/styles.css`
- `home_display/web/src/surfaces/StateSurface.svelte`
- `home_display/web/src/App.test.ts` and `src/surfaces/StateSurface.test.ts`
- Web entry/config/dependency updates: `index.html`, `package.json`, `package-lock.json`, `svelte.config.js`, and `vite.config.ts`
- Compiled assets under `home_display/static/`

Validation:

- RED: `npm test -- src/surfaces/StateSurface.test.ts` failed as expected because `StateSurface.svelte` did not exist.
- `npm test`: PASS — 4 files, 27 tests.
- `npm run check`: PASS — 0 errors, 0 warnings.
- `npm run build`: PASS — output in `home_display/static/`.
- `git diff --check`: PASS before commit.
- `venv/bin/pytest`: no tests were collected and pytest exited 5; this worktree currently has no discoverable Python tests, so it is not a passing repository-level gate.

Concerns:

- Vite minification generated a JavaScript line that violates `git diff --check` because of a trailing space embedded in generated output. The production bundle is intentionally built with `minify: false` so the required whitespace gate passes. This increases the checked-in JavaScript asset size.

## Fix round 1 report

Reviewer finding: buffering, error, and disconnected states were not explicitly actionable when `status_text` was null.

Commit: `e4b32803a846f1d541173d4232b5781c78c93a2c` (`fix: make home display fallback status actionable`)

Changes:

- Split concise state labels from fallback status copy in `StateSurface.svelte`.
- Added null-status fallbacks: `Still working — please wait`, `Something needs attention — try again`, and `Display disconnected — check the host connection`.
- Kept server-provided `status_text` precedence over fallback copy.
- Added focused tests for all three fallback states, server-status preservation, stale disconnected response suppression, and the existing single stable response region.
- Rebuilt the matching asset in `home_display/static/`.

Validation:

- RED: focused surface tests initially failed for the three missing actionable fallback messages.
- `npm test`: PASS — 4 files, 31 tests.
- `npm run check`: PASS — 0 errors, 0 warnings.
- `npm run build`: PASS — output in `home_display/static/`.
- `git diff --check`: PASS before commit.

Concerns: none introduced by this fix round. The original Task 4 report's unminified generated-asset concern remains unchanged.

## Final-review fix round

The browser final review found that reconnecting could expose stale snapshot
state and response text, and that protocol errors did not force an error
surface or clear the stale response. StateSurface now treats every
non-connected channel state as disconnected unless a protocol error is
present; protocol errors take precedence, render the error surface, and keep
the response region empty. App clears the stored protocol error when a valid
snapshot arrives, allowing normal rendering to recover.

Added focused regression coverage for stale speaking content during
connecting, safe protocol-error rendering, and App recovery after a valid
snapshot. Rebuilt the generated assets under `home_display/static/`.

Validation:

- RED: the new StateSurface/App tests initially failed on stale connecting
  content and missing protocol-error state handling.
- `npm --prefix home_display/web test`: 4 files, 34 passed
- `npm --prefix home_display/web run check`: 0 errors, 0 warnings
- `npm --prefix home_display/web run build`: passed; output rebuilt under
  `home_display/static/`
- `git diff --check`: clean

The design status was corrected from “implementation not started” to
“implementation complete; pending final visual review.” No design decisions
were changed. No Python, plan, or ledger files were modified.

## Final-review fix round 1

The final browser review found that duplicate or older valid snapshots were
filtered before App could clear a visible protocol error. StateChannel now
exposes an optional `onValidSnapshot` recovery callback after the existing
socket-factory argument. It fires for every successfully parsed snapshot
before sequence filtering, while `onSnapshot` remains newer-sequence-only.
App clears `protocolError` through this explicit recovery signal, including
when the valid snapshot is not delivered because its sequence is stale.

Added focused regression coverage for malformed data followed by duplicate
and older valid snapshots, including the distinction between recovery signals
and `onSnapshot` delivery. Updated the App mock/lifecycle test and rebuilt
`home_display/static/`.

Validation:

- RED: the new channel and App recovery tests failed before the recovery
  callback was implemented.
- `npm --prefix home_display/web test`: 4 files, 35 passed
- `npm --prefix home_display/web run check`: 0 errors, 0 warnings
- `npm --prefix home_display/web run build`: passed; output rebuilt under
  `home_display/static/`
- `git diff --check`: clean

No Python, plan, or ledger files were modified. The existing physical
two-metre/browser automation review limitation remains.
