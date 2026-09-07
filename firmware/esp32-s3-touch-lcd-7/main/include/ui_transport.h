#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "ui_snapshot.h"

#define UI_TRANSPORT_DISPLAY_PATH "/state"

typedef enum {
    UI_TRANSPORT_STOPPED = 0,
    UI_TRANSPORT_CONNECTING,
    UI_TRANSPORT_CONNECTED,
    UI_TRANSPORT_DISCONNECTED,
    UI_TRANSPORT_ERROR,
} ui_transport_state_t;

typedef void (*ui_transport_snapshot_cb)(const ui_snapshot_t *snapshot, void *user_data);
typedef void (*ui_transport_state_cb)(ui_transport_state_t state, void *user_data);

typedef struct {
    const char *uri;
    ui_transport_snapshot_cb on_snapshot;
    ui_transport_state_cb on_state;
    void *user_data;
    uint32_t reconnect_timeout_ms;
} ui_transport_config_t;

esp_err_t ui_transport_start(const ui_transport_config_t *config);
esp_err_t ui_transport_stop(void);
bool ui_transport_is_connected(void);
