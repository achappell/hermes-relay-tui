"""Host-side tests for the portable display business-rules reducer."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DISPLAY_DIR = REPO_ROOT / "shared" / "display"


def _compile_and_run(source: str) -> subprocess.CompletedProcess[str]:
    harness = Path(__file__).with_name("_display_rules_harness.c")
    binary = Path(__file__).with_name("_display_rules_harness")
    harness.write_text(source)
    try:
        compile_result = subprocess.run(
            [
                "cc",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(DISPLAY_DIR),
                str(harness),
                str(DISPLAY_DIR / "display_rules.c"),
                "-o",
                str(binary),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert compile_result.returncode == 0, compile_result.stderr
        return subprocess.run([str(binary)], check=False, capture_output=True, text=True)
    finally:
        harness.unlink(missing_ok=True)
        binary.unlink(missing_ok=True)


def test_reducer_accepts_the_display_state_path_and_derives_surface_flags() -> None:
    result = _compile_and_run(
        r'''
        #include <assert.h>
        #include <string.h>
        #include "display_rules.h"

        static display_rules_snapshot_t snapshot(uint32_t sequence, display_rules_state_t state) {
            display_rules_snapshot_t value;
            memset(&value, 0, sizeof(value));
            value.schema = 1;
            value.sequence = sequence;
            value.state = state;
            return value;
        }

        int main(void) {
            display_rules_reducer_t reducer;
            display_rules_init(&reducer);

            display_rules_snapshot_t value = snapshot(0, DISPLAY_RULES_IDLE);
            assert(display_rules_apply_snapshot(&reducer, &value) == DISPLAY_RULES_ACCEPTED);
            assert(display_rules_view(&reducer)->state == DISPLAY_RULES_IDLE);
            assert(!display_rules_view(&reducer)->is_busy);
            assert(display_rules_view(&reducer)->connection_healthy);

            value = snapshot(1, DISPLAY_RULES_HEARD);
            assert(display_rules_apply_snapshot(&reducer, &value) == DISPLAY_RULES_ACCEPTED);
            value = snapshot(2, DISPLAY_RULES_LISTENING);
            assert(display_rules_apply_snapshot(&reducer, &value) == DISPLAY_RULES_ACCEPTED);
            value = snapshot(3, DISPLAY_RULES_THINKING);
            assert(display_rules_apply_snapshot(&reducer, &value) == DISPLAY_RULES_ACCEPTED);
            value = snapshot(4, DISPLAY_RULES_SPEAKING);
            assert(display_rules_apply_snapshot(&reducer, &value) == DISPLAY_RULES_ACCEPTED);
            assert(display_rules_view(&reducer)->is_busy);
            value = snapshot(5, DISPLAY_RULES_BUFFERING);
            assert(display_rules_apply_snapshot(&reducer, &value) == DISPLAY_RULES_ACCEPTED);
            value = snapshot(6, DISPLAY_RULES_SPEAKING);
            assert(display_rules_apply_snapshot(&reducer, &value) == DISPLAY_RULES_ACCEPTED);
            value = snapshot(7, DISPLAY_RULES_IDLE);
            assert(display_rules_apply_snapshot(&reducer, &value) == DISPLAY_RULES_ACCEPTED);
            assert(!display_rules_view(&reducer)->is_busy);
            value = snapshot(8, DISPLAY_RULES_DISCONNECTED);
            assert(display_rules_apply_snapshot(&reducer, &value) == DISPLAY_RULES_ACCEPTED);
            assert(!display_rules_view(&reducer)->connection_healthy);
            value = snapshot(9, DISPLAY_RULES_ERROR);
            assert(display_rules_apply_snapshot(&reducer, &value) == DISPLAY_RULES_ACCEPTED);
            assert(display_rules_apply_snapshot(&reducer, &value) == DISPLAY_RULES_STALE);
            value = snapshot(10, DISPLAY_RULES_IDLE);
            assert(display_rules_apply_snapshot(&reducer, &value) == DISPLAY_RULES_ACCEPTED);
            assert(display_rules_view(&reducer)->connection_healthy);
            return 0;
        }
        '''
    )
    assert result.returncode == 0, result.stderr


def test_reducer_rejects_an_invalid_transition_without_mutating_state() -> None:
    result = _compile_and_run(
        r'''
        #include <assert.h>
        #include <string.h>
        #include "display_rules.h"

        int main(void) {
            display_rules_reducer_t reducer;
            display_rules_init(&reducer);
            display_rules_snapshot_t idle = { .schema = 1, .sequence = 0, .state = DISPLAY_RULES_IDLE };
            display_rules_snapshot_t speaking = { .schema = 1, .sequence = 1, .state = DISPLAY_RULES_SPEAKING };
            assert(display_rules_apply_snapshot(&reducer, &idle) == DISPLAY_RULES_ACCEPTED);
            assert(display_rules_apply_snapshot(&reducer, &speaking) == DISPLAY_RULES_INVALID_TRANSITION);
            assert(display_rules_view(&reducer)->state == DISPLAY_RULES_IDLE);
            assert(display_rules_view(&reducer)->sequence == 0);
            return 0;
        }
        '''
    )
    assert result.returncode == 0, result.stderr


def test_reducer_accepts_a_browser_turn_starting_at_thinking() -> None:
    result = _compile_and_run(
        r'''
        #include <assert.h>
        #include "display_rules.h"

        int main(void) {
            display_rules_reducer_t reducer;
            display_rules_init(&reducer);
            display_rules_snapshot_t idle = { .schema = 1, .sequence = 0, .state = DISPLAY_RULES_IDLE };
            display_rules_snapshot_t thinking = { .schema = 1, .sequence = 1, .state = DISPLAY_RULES_THINKING };
            assert(display_rules_apply_snapshot(&reducer, &idle) == DISPLAY_RULES_ACCEPTED);
            assert(display_rules_apply_snapshot(&reducer, &thinking) == DISPLAY_RULES_ACCEPTED);
            assert(display_rules_view(&reducer)->state == DISPLAY_RULES_THINKING);
            assert(display_rules_view(&reducer)->is_busy);
            return 0;
        }
        '''
    )
    assert result.returncode == 0, result.stderr


def test_reducer_rejects_stale_snapshots_without_mutating_state() -> None:
    result = _compile_and_run(
        r'''
        #include <assert.h>
        #include "display_rules.h"

        int main(void) {
            display_rules_reducer_t reducer;
            display_rules_init(&reducer);
            display_rules_snapshot_t current = { .schema = 1, .sequence = 5, .state = DISPLAY_RULES_LISTENING };
            display_rules_snapshot_t duplicate = { .schema = 1, .sequence = 5, .state = DISPLAY_RULES_IDLE };
            display_rules_snapshot_t older = { .schema = 1, .sequence = 4, .state = DISPLAY_RULES_IDLE };
            assert(display_rules_apply_snapshot(&reducer, &current) == DISPLAY_RULES_ACCEPTED);
            assert(display_rules_apply_snapshot(&reducer, &duplicate) == DISPLAY_RULES_STALE);
            assert(display_rules_apply_snapshot(&reducer, &older) == DISPLAY_RULES_STALE);
            assert(display_rules_view(&reducer)->state == DISPLAY_RULES_LISTENING);
            assert(display_rules_view(&reducer)->sequence == 5);
            return 0;
        }
        '''
    )
    assert result.returncode == 0, result.stderr


def test_prompt_actions_are_validated_without_mutating_the_reducer() -> None:
    result = _compile_and_run(
        r'''
        #include <assert.h>
        #include <string.h>
        #include "display_rules.h"

        int main(void) {
            display_rules_reducer_t reducer;
            display_rules_init(&reducer);
            display_rules_snapshot_t prompt;
            memset(&prompt, 0, sizeof(prompt));
            prompt.schema = 1;
            prompt.sequence = 1;
            prompt.state = DISPLAY_RULES_PROMPT;
            prompt.prompt.present = true;
            prompt.prompt.can_choose = true;
            prompt.prompt.can_dismiss = false;
            strcpy(prompt.prompt.action_id, "sethome");
            prompt.prompt.option_count = 2;
            strcpy(prompt.prompt.options[0].id, "yes");
            strcpy(prompt.prompt.options[1].id, "no");
            assert(display_rules_apply_snapshot(&reducer, &prompt) == DISPLAY_RULES_ACCEPTED);

            assert(display_rules_validate_choice(&reducer, "sethome", "yes") == DISPLAY_RULES_ACCEPTED);
            assert(display_rules_validate_choice(&reducer, "other", "yes") == DISPLAY_RULES_ACTION_ID_MISMATCH);
            assert(display_rules_validate_choice(&reducer, "sethome", "later") == DISPLAY_RULES_UNKNOWN_CHOICE);
            assert(display_rules_validate_dismiss(&reducer) == DISPLAY_RULES_ACTION_NOT_ALLOWED);
            assert(display_rules_view(&reducer)->state == DISPLAY_RULES_PROMPT);
            assert(display_rules_view(&reducer)->sequence == 1);
            return 0;
        }
        '''
    )
    assert result.returncode == 0, result.stderr


def test_invalid_snapshot_is_rejected_without_mutating_the_reducer() -> None:
    result = _compile_and_run(
        r'''
        #include <assert.h>
        #include <string.h>
        #include "display_rules.h"

        int main(void) {
            display_rules_reducer_t reducer;
            display_rules_init(&reducer);
            display_rules_snapshot_t idle = { .schema = 1, .sequence = 1, .state = DISPLAY_RULES_IDLE };
            display_rules_snapshot_t malformed;
            memset(&malformed, 0, sizeof(malformed));
            malformed.schema = 1;
            malformed.sequence = 2;
            malformed.state = DISPLAY_RULES_PROMPT;
            malformed.prompt.present = false;
            assert(display_rules_apply_snapshot(&reducer, &idle) == DISPLAY_RULES_ACCEPTED);
            assert(display_rules_apply_snapshot(&reducer, &malformed) == DISPLAY_RULES_INVALID_SNAPSHOT);
            assert(display_rules_view(&reducer)->state == DISPLAY_RULES_IDLE);
            assert(display_rules_view(&reducer)->sequence == 1);
            return 0;
        }
        '''
    )
    assert result.returncode == 0, result.stderr
