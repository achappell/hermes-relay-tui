# Task 3 report: browser protocol and reconnecting channel

## Original implementation

Implemented the Task 3 browser scaffold, schema-1 snapshot parser, and
injectable reconnecting `StateChannel` in commit `861b84a`. The original
task report was not present in this worktree when the fix round began.

## Fix round 1

Added focused regression tests before changing production code for consumer
callback failures and stopping with a reconnect timer pending. Public
snapshot, connection-state, and protocol-error delivery now runs through an
exception boundary so consumer exceptions cannot escape WebSocket event
callbacks. Existing channel behavior remains intact: malformed data still
reports `display data unavailable`, stale sequences remain filtered, socket
open resets the accepted sequence, and reconnect backoff/timer cleanup are
unchanged.

Validation:

- `npm --prefix home_display/web test`: 17 passed
- `npm --prefix home_display/web run check`: 0 errors, 1 expected warning
  because Task 3 intentionally contains no Svelte input files
- `npm --prefix home_display/web run build`: passed
- `git diff --check`: clean

The fix is limited to `home_display/web` behavior/tests plus this report.
