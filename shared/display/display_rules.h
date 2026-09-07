#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define DISPLAY_RULES_ACTION_ID_MAX 64
#define DISPLAY_RULES_OPTION_COUNT_MAX 4
#define DISPLAY_RULES_OPTION_ID_MAX 32

typedef enum {
    DISPLAY_RULES_UNKNOWN = 0,
    DISPLAY_RULES_IDLE,
    DISPLAY_RULES_HEARD,
    DISPLAY_RULES_LISTENING,
    DISPLAY_RULES_THINKING,
    DISPLAY_RULES_SPEAKING,
    DISPLAY_RULES_BUFFERING,
    DISPLAY_RULES_ERROR,
    DISPLAY_RULES_DISCONNECTED,
    DISPLAY_RULES_PROMPT,
} display_rules_state_t;

typedef struct {
    char id[DISPLAY_RULES_OPTION_ID_MAX];
} display_rules_option_t;

typedef struct {
    bool present;
    bool can_choose;
    bool can_dismiss;
    char action_id[DISPLAY_RULES_ACTION_ID_MAX];
    uint8_t option_count;
    display_rules_option_t options[DISPLAY_RULES_OPTION_COUNT_MAX];
} display_rules_prompt_t;

typedef struct {
    uint8_t schema;
    uint32_t sequence;
    display_rules_state_t state;
    display_rules_prompt_t prompt;
} display_rules_snapshot_t;

typedef struct {
    bool initialized;
    uint32_t sequence;
    display_rules_state_t state;
    bool is_busy;
    bool connection_healthy;
    bool can_choose;
    bool can_dismiss;
    display_rules_prompt_t prompt;
} display_rules_view_t;

typedef struct {
    display_rules_view_t current;
} display_rules_reducer_t;

typedef enum {
    DISPLAY_RULES_ACCEPTED = 0,
    DISPLAY_RULES_STALE,
    DISPLAY_RULES_INVALID_ARGUMENT,
    DISPLAY_RULES_INVALID_SNAPSHOT,
    DISPLAY_RULES_INVALID_TRANSITION,
    DISPLAY_RULES_PROMPT_NOT_ACTIVE,
    DISPLAY_RULES_ACTION_NOT_ALLOWED,
    DISPLAY_RULES_ACTION_ID_MISMATCH,
    DISPLAY_RULES_UNKNOWN_CHOICE,
} display_rules_result_t;

void display_rules_init(display_rules_reducer_t *reducer);

display_rules_result_t display_rules_apply_snapshot(
    display_rules_reducer_t *reducer,
    const display_rules_snapshot_t *snapshot
);

const display_rules_view_t *display_rules_view(const display_rules_reducer_t *reducer);

display_rules_result_t display_rules_validate_choice(
    const display_rules_reducer_t *reducer,
    const char *action_id,
    const char *choice
);

display_rules_result_t display_rules_validate_dismiss(
    const display_rules_reducer_t *reducer
);
