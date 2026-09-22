#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "ui_snapshot.h"

#define UI_TRANSPORT_DISPLAY_PATH "/state"
#define UI_TRANSPORT_MESSAGE_MAX 65536

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
esp_err_t ui_transport_send_action(
    const char *action_id,
    const char *option_id,
    const char *operation,
    const char *object_id,
    const char *freshness
);
bool ui_transport_is_connected(void);

/* Called only by the capture worker; controls and PCM share ordering. */
esp_err_t ui_transport_send_text(const char *text);
esp_err_t ui_transport_send_pcm(const void *pcm, size_t size);
void ui_transport_invalidate(void);
bool ui_transport_needs_restart(void);

/* Epoch is checked under the same lifetime lock that guards socket replacement. */
esp_err_t ui_transport_send_text_epoch(const char *text, uint32_t epoch);
esp_err_t ui_transport_send_pcm_epoch(const void *pcm, size_t size, uint32_t epoch);
void ui_transport_invalidate_epoch(uint32_t epoch);
