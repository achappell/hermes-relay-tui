#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "ui_snapshot.h"

typedef void (*ui_display_action_cb)(const char *action_id, const char *choice, void *user_data);

bool ui_display_init(ui_display_action_cb action_cb, void *user_data);
void ui_display_set_snapshot(const ui_snapshot_t *snapshot);
void ui_display_update_diagnostics(bool touch_active, uint16_t x, uint16_t y, uint8_t point_count, uint32_t fps);
