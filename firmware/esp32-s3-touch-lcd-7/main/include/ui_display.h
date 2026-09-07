#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "ui_snapshot.h"

typedef void (*ui_display_action_cb)(const char *action_id, const char *choice, void *user_data);

typedef enum {
    UI_DISPLAY_CONNECTION_CONNECTED = 0,
    UI_DISPLAY_CONNECTION_DISCONNECTED,
    UI_DISPLAY_CONNECTION_ERROR,
} ui_display_connection_state_t;

bool ui_display_init(ui_display_action_cb action_cb, void *user_data);
display_rules_result_t ui_display_set_snapshot(const ui_snapshot_t *snapshot);
display_rules_result_t ui_display_set_connection_state(ui_display_connection_state_t state);
display_rules_result_t ui_display_validate_choice(const char *action_id, const char *choice);
display_rules_result_t ui_display_validate_dismiss(void);
const display_rules_view_t *ui_display_rules_view(void);
void ui_display_update_diagnostics(bool touch_active, uint16_t x, uint16_t y, uint8_t point_count, uint32_t fps);
