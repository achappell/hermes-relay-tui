#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "display_rules.h"

#define UI_SNAPSHOT_RESPONSE_TEXT_MAX 512
#define UI_SNAPSHOT_STATUS_TEXT_MAX 96
#define UI_SNAPSHOT_ACCOUNT_MAX 48
#define UI_SNAPSHOT_PROMPT_KIND_MAX 24
#define UI_SNAPSHOT_PROMPT_TITLE_MAX 64
#define UI_SNAPSHOT_PROMPT_BODY_MAX 192
#define UI_SNAPSHOT_ACTION_ID_MAX 64
#define UI_SNAPSHOT_OPTION_COUNT_MAX 4
#define UI_SNAPSHOT_OPTION_ID_MAX 32
#define UI_SNAPSHOT_OPTION_LABEL_MAX 48

typedef display_rules_state_t ui_display_state_t;

#define UI_DISPLAY_UNKNOWN DISPLAY_RULES_UNKNOWN
#define UI_DISPLAY_IDLE DISPLAY_RULES_IDLE
#define UI_DISPLAY_HEARD DISPLAY_RULES_HEARD
#define UI_DISPLAY_LISTENING DISPLAY_RULES_LISTENING
#define UI_DISPLAY_THINKING DISPLAY_RULES_THINKING
#define UI_DISPLAY_SPEAKING DISPLAY_RULES_SPEAKING
#define UI_DISPLAY_BUFFERING DISPLAY_RULES_BUFFERING
#define UI_DISPLAY_ERROR DISPLAY_RULES_ERROR
#define UI_DISPLAY_DISCONNECTED DISPLAY_RULES_DISCONNECTED
#define UI_DISPLAY_PROMPT DISPLAY_RULES_PROMPT

typedef struct {
    char id[UI_SNAPSHOT_OPTION_ID_MAX];
    char label[UI_SNAPSHOT_OPTION_LABEL_MAX];
} ui_snapshot_option_t;

typedef struct {
    bool present;
    bool can_choose;
    bool can_dismiss;
    char kind[UI_SNAPSHOT_PROMPT_KIND_MAX];
    char title[UI_SNAPSHOT_PROMPT_TITLE_MAX];
    char body[UI_SNAPSHOT_PROMPT_BODY_MAX];
    char action_id[UI_SNAPSHOT_ACTION_ID_MAX];
    int32_t timeout_seconds;
    uint8_t option_count;
    ui_snapshot_option_t options[UI_SNAPSHOT_OPTION_COUNT_MAX];
} ui_snapshot_prompt_t;

typedef struct {
    uint8_t schema;
    uint32_t sequence;
    ui_display_state_t state;
    char response_text[UI_SNAPSHOT_RESPONSE_TEXT_MAX];
    char status_text[UI_SNAPSHOT_STATUS_TEXT_MAX];
    char account[UI_SNAPSHOT_ACCOUNT_MAX];
    ui_snapshot_prompt_t prompt;
} ui_snapshot_t;

ui_display_state_t ui_display_state_from_name(const char *name);
const char *ui_display_state_name(ui_display_state_t state);

bool ui_snapshot_init(ui_snapshot_t *snapshot);
bool ui_snapshot_set_state(ui_snapshot_t *snapshot, const char *name);
bool ui_snapshot_set_text(ui_snapshot_t *snapshot, const char *response_text, const char *status_text);
bool ui_snapshot_from_json(const char *json, ui_snapshot_t *snapshot);
bool ui_snapshot_to_rules(const ui_snapshot_t *snapshot, display_rules_snapshot_t *rules_snapshot);
