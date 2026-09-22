#include "display_rules.h"

#include <string.h>

static bool bounded_nonempty(const char *value, size_t capacity)
{
    if (value == NULL || capacity == 0) return false;
    for (size_t index = 0; index < capacity; index++) {
        if (value[index] == '\0') return index > 0;
    }
    return false;
}

static bool known_state(display_rules_state_t state)
{
    return state >= DISPLAY_RULES_IDLE && state <= DISPLAY_RULES_STATE_LAST;
}

static bool busy_state(display_rules_state_t state)
{
    return state == DISPLAY_RULES_LISTENING ||
           state == DISPLAY_RULES_TRANSCRIBING ||
           state == DISPLAY_RULES_THINKING ||
           state == DISPLAY_RULES_SPEAKING ||
           state == DISPLAY_RULES_BUFFERING;
}

static bool healthy_state(display_rules_state_t state)
{
    return state != DISPLAY_RULES_ERROR && state != DISPLAY_RULES_DISCONNECTED;
}

static bool transition_allowed(display_rules_state_t current, display_rules_state_t next)
{
    if (current == next || next == DISPLAY_RULES_ERROR || next == DISPLAY_RULES_DISCONNECTED) {
        return true;
    }

    switch (current) {
        case DISPLAY_RULES_IDLE:
            return next == DISPLAY_RULES_HEARD ||
                   next == DISPLAY_RULES_LISTENING ||
                   next == DISPLAY_RULES_THINKING ||
                   next == DISPLAY_RULES_PROMPT;
        case DISPLAY_RULES_HEARD:
            return next == DISPLAY_RULES_LISTENING ||
                   next == DISPLAY_RULES_THINKING ||
                   next == DISPLAY_RULES_IDLE ||
                   next == DISPLAY_RULES_PROMPT;
        case DISPLAY_RULES_LISTENING:
            return next == DISPLAY_RULES_TRANSCRIBING ||
                   next == DISPLAY_RULES_THINKING ||
                   next == DISPLAY_RULES_HEARD ||
                   next == DISPLAY_RULES_IDLE;
        /* Transcription is a local, pre-submission phase: it may reach a
           submitted turn or fall back to idle, but it can never jump straight
           to a response phase, because no prompt has been sent yet. */
        case DISPLAY_RULES_TRANSCRIBING:
            return next == DISPLAY_RULES_THINKING ||
                   next == DISPLAY_RULES_HEARD ||
                   next == DISPLAY_RULES_IDLE;
        case DISPLAY_RULES_THINKING:
            return next == DISPLAY_RULES_SPEAKING ||
                   next == DISPLAY_RULES_BUFFERING ||
                   next == DISPLAY_RULES_PROMPT ||
                   next == DISPLAY_RULES_COMPLETE ||
                   next == DISPLAY_RULES_IDLE;
        case DISPLAY_RULES_SPEAKING:
            return next == DISPLAY_RULES_BUFFERING ||
                   next == DISPLAY_RULES_PROMPT ||
                   next == DISPLAY_RULES_COMPLETE ||
                   next == DISPLAY_RULES_IDLE;
        case DISPLAY_RULES_BUFFERING:
            return next == DISPLAY_RULES_SPEAKING ||
                   next == DISPLAY_RULES_THINKING ||
                   next == DISPLAY_RULES_PROMPT ||
                   next == DISPLAY_RULES_COMPLETE ||
                   next == DISPLAY_RULES_IDLE;
        /* A completed turn is terminal for its answer. The next thing the
           room may see is another initiation, never a resumed response. */
        case DISPLAY_RULES_COMPLETE:
            return next == DISPLAY_RULES_IDLE ||
                   next == DISPLAY_RULES_HEARD ||
                   next == DISPLAY_RULES_LISTENING ||
                   next == DISPLAY_RULES_THINKING ||
                   next == DISPLAY_RULES_PROMPT;
        case DISPLAY_RULES_ERROR:
            return next == DISPLAY_RULES_IDLE;
        case DISPLAY_RULES_DISCONNECTED:
            return next == DISPLAY_RULES_IDLE ||
                   next == DISPLAY_RULES_HEARD ||
                   next == DISPLAY_RULES_LISTENING;
        case DISPLAY_RULES_PROMPT:
            return next == DISPLAY_RULES_IDLE ||
                   next == DISPLAY_RULES_THINKING ||
                   next == DISPLAY_RULES_PROMPT;
        case DISPLAY_RULES_UNKNOWN:
        default:
            return false;
    }
}

static bool valid_prompt(const display_rules_prompt_t *prompt)
{
    if (prompt == NULL || !prompt->present ||
        !bounded_nonempty(prompt->action_id, sizeof(prompt->action_id)) ||
        prompt->option_count == 0 ||
        prompt->option_count > DISPLAY_RULES_OPTION_COUNT_MAX ||
        (!prompt->typed_choice &&
         prompt->option_count > DISPLAY_RULES_GENERIC_OPTION_COUNT_MAX)) {
        return false;
    }

    for (uint8_t index = 0; index < prompt->option_count; index++) {
        if (!bounded_nonempty(prompt->options[index].id, sizeof(prompt->options[index].id))) {
            return false;
        }
        if (!prompt->typed_choice && strlen(prompt->options[index].id) > 32) {
            return false;
        }
        for (uint8_t previous = 0; previous < index; previous++) {
            if (strcmp(prompt->options[index].id, prompt->options[previous].id) == 0) {
                return false;
            }
        }
    }
    if (prompt->typed_choice) {
        if (!bounded_nonempty(prompt->object_id, sizeof(prompt->object_id)) ||
            !bounded_nonempty(prompt->freshness, sizeof(prompt->freshness)) ||
            (!prompt->allows_choose && !prompt->allows_explore)) {
            return false;
        }
    } else if (prompt->allows_choose || prompt->allows_explore ||
               prompt->object_id[0] != '\0' || prompt->freshness[0] != '\0') {
        return false;
    }
    return true;
}

static bool valid_snapshot(const display_rules_snapshot_t *snapshot)
{
    if (snapshot == NULL || snapshot->schema != 1 || !known_state(snapshot->state)) {
        return false;
    }
    if (snapshot->state == DISPLAY_RULES_PROMPT) {
        return valid_prompt(&snapshot->prompt);
    }
    return !snapshot->prompt.present;
}

void display_rules_init(display_rules_reducer_t *reducer)
{
    if (reducer != NULL) memset(reducer, 0, sizeof(*reducer));
}

display_rules_result_t display_rules_apply_snapshot(
    display_rules_reducer_t *reducer,
    const display_rules_snapshot_t *snapshot
)
{
    if (reducer == NULL || snapshot == NULL) return DISPLAY_RULES_INVALID_ARGUMENT;
    if (!valid_snapshot(snapshot)) return DISPLAY_RULES_INVALID_SNAPSHOT;

    const display_rules_view_t *current = &reducer->current;
    if (current->initialized && snapshot->sequence <= current->sequence) {
        return DISPLAY_RULES_STALE;
    }
    if (current->initialized && !transition_allowed(current->state, snapshot->state)) {
        return DISPLAY_RULES_INVALID_TRANSITION;
    }

    display_rules_view_t next = {
        .initialized = true,
        .sequence = snapshot->sequence,
        .state = snapshot->state,
        .is_busy = busy_state(snapshot->state),
        .connection_healthy = healthy_state(snapshot->state),
        .can_choose = snapshot->state == DISPLAY_RULES_PROMPT &&
                      snapshot->prompt.can_choose &&
                      (!snapshot->prompt.typed_choice || snapshot->prompt.allows_choose),
        .can_explore = snapshot->state == DISPLAY_RULES_PROMPT &&
                       snapshot->prompt.typed_choice &&
                       snapshot->prompt.can_explore &&
                       snapshot->prompt.allows_explore,
        .can_dismiss = snapshot->state == DISPLAY_RULES_PROMPT && snapshot->prompt.can_dismiss,
        .prompt = snapshot->prompt,
    };
    reducer->current = next;
    return DISPLAY_RULES_ACCEPTED;
}

const display_rules_view_t *display_rules_view(const display_rules_reducer_t *reducer)
{
    return reducer == NULL ? NULL : &reducer->current;
}

display_rules_result_t display_rules_validate_choice(
    const display_rules_reducer_t *reducer,
    const char *action_id,
    const char *choice
)
{
    if (reducer == NULL || !bounded_nonempty(action_id, DISPLAY_RULES_ACTION_ID_MAX) ||
        !bounded_nonempty(choice, DISPLAY_RULES_OPTION_ID_MAX)) {
        return DISPLAY_RULES_INVALID_ARGUMENT;
    }
    const display_rules_view_t *current = &reducer->current;
    if (!current->initialized || current->state != DISPLAY_RULES_PROMPT) {
        return DISPLAY_RULES_PROMPT_NOT_ACTIVE;
    }
    if (current->prompt.typed_choice) return DISPLAY_RULES_ACTION_NOT_ALLOWED;
    if (!current->can_choose) return DISPLAY_RULES_ACTION_NOT_ALLOWED;
    if (strcmp(current->prompt.action_id, action_id) != 0) {
        return DISPLAY_RULES_ACTION_ID_MISMATCH;
    }
    for (uint8_t index = 0; index < current->prompt.option_count; index++) {
        if (strcmp(current->prompt.options[index].id, choice) == 0) {
            return DISPLAY_RULES_ACCEPTED;
        }
    }
    return DISPLAY_RULES_UNKNOWN_CHOICE;
}

display_rules_result_t display_rules_validate_typed_choice(
    const display_rules_reducer_t *reducer,
    const char *action_id,
    const char *operation,
    const char *option_id,
    const char *object_id,
    const char *freshness
)
{
    if (reducer == NULL ||
        !bounded_nonempty(action_id, DISPLAY_RULES_ACTION_ID_MAX) ||
        !bounded_nonempty(operation, 8) ||
        !bounded_nonempty(option_id, DISPLAY_RULES_OPTION_ID_MAX) ||
        !bounded_nonempty(object_id, DISPLAY_RULES_CHOICE_CONTEXT_MAX) ||
        !bounded_nonempty(freshness, DISPLAY_RULES_CHOICE_CONTEXT_MAX)) {
        return DISPLAY_RULES_INVALID_ARGUMENT;
    }
    const display_rules_view_t *current = &reducer->current;
    if (!current->initialized || current->state != DISPLAY_RULES_PROMPT) {
        return DISPLAY_RULES_PROMPT_NOT_ACTIVE;
    }
    if (!current->prompt.typed_choice) return DISPLAY_RULES_ACTION_NOT_ALLOWED;
    if (strcmp(current->prompt.action_id, action_id) != 0) {
        return DISPLAY_RULES_ACTION_ID_MISMATCH;
    }
    if (strcmp(current->prompt.object_id, object_id) != 0 ||
        strcmp(current->prompt.freshness, freshness) != 0) {
        return DISPLAY_RULES_CHOICE_CONTEXT_MISMATCH;
    }

    bool permitted = false;
    if (strcmp(operation, "choose") == 0) {
        permitted = current->can_choose;
    } else if (strcmp(operation, "explore") == 0) {
        permitted = current->can_explore;
    } else {
        return DISPLAY_RULES_ACTION_NOT_ALLOWED;
    }
    if (!permitted) return DISPLAY_RULES_ACTION_NOT_ALLOWED;

    for (uint8_t index = 0; index < current->prompt.option_count; index++) {
        if (strcmp(current->prompt.options[index].id, option_id) == 0) {
            return DISPLAY_RULES_ACCEPTED;
        }
    }
    return DISPLAY_RULES_UNKNOWN_CHOICE;
}

display_rules_result_t display_rules_validate_dismiss(
    const display_rules_reducer_t *reducer
)
{
    if (reducer == NULL) return DISPLAY_RULES_INVALID_ARGUMENT;
    const display_rules_view_t *current = &reducer->current;
    if (!current->initialized || current->state != DISPLAY_RULES_PROMPT) {
        return DISPLAY_RULES_PROMPT_NOT_ACTIVE;
    }
    return current->can_dismiss ? DISPLAY_RULES_ACCEPTED : DISPLAY_RULES_ACTION_NOT_ALLOWED;
}
