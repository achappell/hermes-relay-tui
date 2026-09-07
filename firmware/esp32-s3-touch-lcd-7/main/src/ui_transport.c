#include "ui_transport.h"

#include "cJSON.h"
#include "esp_log.h"
#include "esp_websocket_client.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <stdlib.h>
#include <string.h>

#define UI_TRANSPORT_DEFAULT_RECONNECT_TIMEOUT_MS 5000
#define UI_TRANSPORT_BUFFER_SIZE 4096
#define UI_TRANSPORT_MESSAGE_MAX 4096

static const char *TAG = "ui_transport";

typedef struct {
    esp_websocket_client_handle_t client;
    ui_transport_config_t config;
    char message[UI_TRANSPORT_MESSAGE_MAX];
    size_t received;
    size_t expected;
    bool assembling;
    bool connected;
    bool stopping;
} ui_transport_context_t;

static ui_transport_context_t s_transport;

static void notify_state(ui_transport_state_t state)
{
    if (s_transport.config.on_state != NULL) {
        s_transport.config.on_state(state, s_transport.config.user_data);
    }
}

static void reset_message(void)
{
    s_transport.received = 0;
    s_transport.expected = 0;
    s_transport.assembling = false;
}

static void handle_text_frame(const esp_websocket_event_data_t *event)
{
    if (event == NULL || event->data_ptr == NULL || event->data_len < 0 || event->payload_len < 0 ||
        (size_t)event->payload_len >= sizeof(s_transport.message)) {
        reset_message();
        notify_state(UI_TRANSPORT_ERROR);
        return;
    }

    if (event->payload_offset == 0) {
        reset_message();
        s_transport.expected = (size_t)event->payload_len;
        s_transport.assembling = true;
    }

    if (!s_transport.assembling || (size_t)event->payload_offset != s_transport.received ||
        s_transport.received + (size_t)event->data_len >= sizeof(s_transport.message)) {
        reset_message();
        notify_state(UI_TRANSPORT_ERROR);
        return;
    }

    memcpy(s_transport.message + s_transport.received, event->data_ptr, (size_t)event->data_len);
    s_transport.received += (size_t)event->data_len;

    if (!event->fin) return;
    if (s_transport.received != s_transport.expected) {
        reset_message();
        notify_state(UI_TRANSPORT_ERROR);
        return;
    }

    s_transport.message[s_transport.received] = '\0';
    ui_snapshot_t snapshot;
    if (!ui_snapshot_from_json(s_transport.message, &snapshot)) {
        ESP_LOGW(TAG, "Ignoring malformed display snapshot");
        reset_message();
        return;
    }
    if (s_transport.config.on_snapshot != NULL) {
        s_transport.config.on_snapshot(&snapshot, s_transport.config.user_data);
    }
    reset_message();
}

static void websocket_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data)
{
    (void)handler_args;
    (void)base;

    switch ((esp_websocket_event_id_t)event_id) {
        case WEBSOCKET_EVENT_BEGIN:
            notify_state(UI_TRANSPORT_CONNECTING);
            break;
        case WEBSOCKET_EVENT_CONNECTED:
            s_transport.connected = true;
            notify_state(UI_TRANSPORT_CONNECTED);
            break;
        case WEBSOCKET_EVENT_DATA:
            if (event_data != NULL) {
                handle_text_frame((const esp_websocket_event_data_t *)event_data);
            }
            break;
        case WEBSOCKET_EVENT_ERROR:
            notify_state(UI_TRANSPORT_ERROR);
            break;
        case WEBSOCKET_EVENT_DISCONNECTED:
        case WEBSOCKET_EVENT_CLOSED:
            s_transport.connected = false;
            notify_state(s_transport.stopping ? UI_TRANSPORT_STOPPED : UI_TRANSPORT_DISCONNECTED);
            break;
        case WEBSOCKET_EVENT_FINISH:
            s_transport.connected = false;
            break;
        default:
            break;
    }
}

esp_err_t ui_transport_start(const ui_transport_config_t *config)
{
    if (config == NULL || config->uri == NULL || config->uri[0] == '\0' || config->on_snapshot == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_transport.client != NULL) return ESP_ERR_INVALID_STATE;

    memset(&s_transport, 0, sizeof(s_transport));
    s_transport.config = *config;
    s_transport.stopping = false;
    notify_state(UI_TRANSPORT_CONNECTING);

    esp_websocket_client_config_t websocket_config = {
        .uri = config->uri,
        .user_context = &s_transport,
        .buffer_size = UI_TRANSPORT_BUFFER_SIZE,
        .disable_auto_reconnect = false,
        .enable_close_reconnect = true,
        .reconnect_timeout_ms = config->reconnect_timeout_ms != 0
            ? (int)config->reconnect_timeout_ms
            : UI_TRANSPORT_DEFAULT_RECONNECT_TIMEOUT_MS,
    };
    s_transport.client = esp_websocket_client_init(&websocket_config);
    if (s_transport.client == NULL) {
        notify_state(UI_TRANSPORT_ERROR);
        return ESP_FAIL;
    }

    esp_err_t err = esp_websocket_register_events(
        s_transport.client, WEBSOCKET_EVENT_ANY, websocket_event_handler, &s_transport);
    if (err != ESP_OK) {
        esp_websocket_client_destroy(s_transport.client);
        s_transport.client = NULL;
        notify_state(UI_TRANSPORT_ERROR);
        return err;
    }

    err = esp_websocket_client_start(s_transport.client);
    if (err != ESP_OK) {
        esp_websocket_client_destroy(s_transport.client);
        s_transport.client = NULL;
        notify_state(UI_TRANSPORT_ERROR);
    }
    return err;
}

esp_err_t ui_transport_stop(void)
{
    if (s_transport.client == NULL) {
        notify_state(UI_TRANSPORT_STOPPED);
        return ESP_OK;
    }
    s_transport.stopping = true;
    esp_err_t err = esp_websocket_client_stop(s_transport.client);
    esp_err_t destroy_err = esp_websocket_client_destroy(s_transport.client);
    s_transport.client = NULL;
    s_transport.connected = false;
    reset_message();
    notify_state(UI_TRANSPORT_STOPPED);
    return err != ESP_OK ? err : destroy_err;
}

bool ui_transport_is_connected(void)
{
    return s_transport.connected;
}

esp_err_t ui_transport_send_action(const char *action_id, const char *choice)
{
    if (action_id == NULL || action_id[0] == '\0' || choice == NULL || choice[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_transport.client == NULL || !s_transport.connected) return ESP_ERR_INVALID_STATE;

    cJSON *action = cJSON_CreateObject();
    if (action == NULL ||
        !cJSON_AddStringToObject(action, "type", "action") ||
        !cJSON_AddNumberToObject(action, "schema", 1) ||
        !cJSON_AddStringToObject(action, "action_id", action_id) ||
        !cJSON_AddStringToObject(action, "choice", choice)) {
        cJSON_Delete(action);
        return ESP_ERR_NO_MEM;
    }

    char *payload = cJSON_PrintUnformatted(action);
    cJSON_Delete(action);
    if (payload == NULL) return ESP_ERR_NO_MEM;

    int sent = esp_websocket_client_send_text(
        s_transport.client,
        payload,
        strlen(payload),
        pdMS_TO_TICKS(1000));
    cJSON_free(payload);
    return sent < 0 ? ESP_FAIL : ESP_OK;
}
