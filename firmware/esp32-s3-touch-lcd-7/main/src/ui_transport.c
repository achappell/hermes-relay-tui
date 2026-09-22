#include "ui_transport.h"
#include "touch_capture.h"
#include "sdkconfig.h"

#include "cJSON.h"
#include "esp_log.h"
#include "esp_websocket_client.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

#include <stdlib.h>
#include <string.h>

#define UI_TRANSPORT_DEFAULT_RECONNECT_TIMEOUT_MS 5000
#define UI_TRANSPORT_BUFFER_SIZE 4096

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
static ui_snapshot_t s_parsed_snapshot;
static uint32_t s_epoch;
static bool s_restart;
static portMUX_TYPE s_state_lock = portMUX_INITIALIZER_UNLOCKED;
static bool s_binary;
static SemaphoreHandle_t s_send_mutex;

static uint32_t connection_epoch(void)
{
    portENTER_CRITICAL(&s_state_lock);
    uint32_t value = s_epoch;
    portEXIT_CRITICAL(&s_state_lock);
    return value;
}
static bool connection_matches(uint32_t epoch)
{
    portENTER_CRITICAL(&s_state_lock);
    bool value = s_transport.connected && s_epoch == epoch;
    portEXIT_CRITICAL(&s_state_lock);
    return value;
}
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

static void frame_error(uint32_t epoch)
{
    reset_message();
#ifdef CONFIG_TOUCH_VOICE
    ui_transport_invalidate_epoch(epoch);
#else
    (void)epoch;
    notify_state(UI_TRANSPORT_ERROR);
#endif
}

static void handle_text_frame(const esp_websocket_event_data_t *event, uint32_t epoch)
{
    if (event == NULL || event->data_ptr == NULL || event->data_len < 0 || event->payload_len < 0 || event->payload_offset < 0 ||
        (size_t)event->payload_len >= sizeof(s_transport.message)) {
        frame_error(epoch);
        return;
    }

    if (event->payload_offset == 0) {
#ifdef CONFIG_TOUCH_VOICE
        if (s_transport.assembling) { frame_error(epoch); return; }
#endif
        reset_message();
        s_transport.expected = (size_t)event->payload_len;
        s_transport.assembling = true;
    }

    if (!s_transport.assembling || (size_t)event->payload_offset != s_transport.received ||
        (size_t)event->payload_len != s_transport.expected ||
        (size_t)event->data_len > s_transport.expected - s_transport.received ||
        s_transport.received + (size_t)event->data_len >= sizeof(s_transport.message)) {
        frame_error(epoch);
        return;
    }

    memcpy(s_transport.message + s_transport.received, event->data_ptr, (size_t)event->data_len);
    s_transport.received += (size_t)event->data_len;

    /* IDF repeats the RFC-frame FIN bit on every receive-buffer chunk. */
    if (s_transport.received < s_transport.expected) return;
    if (!event->fin) {
#ifdef CONFIG_TOUCH_VOICE
        frame_error(epoch); /* RFC fragmented messages are not supported here. */
#endif
        return;
    }

    s_transport.message[s_transport.received] = '\0';
#ifdef CONFIG_TOUCH_VOICE
    cJSON *object = cJSON_Parse(s_transport.message);
    cJSON *type = object ? cJSON_GetObjectItem(object, "type") : NULL;
    if (!cJSON_IsString(type)) {
        cJSON_Delete(object);
        frame_error(epoch);
        return;
    }
    bool control = strcmp(type->valuestring, "snapshot") != 0;
    cJSON_Delete(object);
    if (control) {
        touch_capture_control(s_transport.message, epoch);
        reset_message();
        return;
    }
#endif
    if (!ui_snapshot_from_json(s_transport.message, &s_parsed_snapshot)) {
        ESP_LOGW(TAG, "Ignoring malformed display snapshot");
        reset_message();
        return;
    }
    if (connection_matches(epoch) && s_transport.config.on_snapshot != NULL) {
        s_transport.config.on_snapshot(&s_parsed_snapshot, s_transport.config.user_data);
    }
    reset_message();
}

static void websocket_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data)
{
    /* stop/destroy completes before replacement; nevertheless reject any
     * queued callback from a retired client before parsing or publishing it. */
    if (handler_args != s_transport.client) return;
    (void)base;

    switch ((esp_websocket_event_id_t)event_id) {
        case WEBSOCKET_EVENT_BEGIN:
            notify_state(UI_TRANSPORT_CONNECTING);
            break;
        case WEBSOCKET_EVENT_CONNECTED:
            portENTER_CRITICAL(&s_state_lock);
            if (s_restart || s_transport.stopping) {
                portEXIT_CRITICAL(&s_state_lock);
                break;
            }
            ++s_epoch;
            s_transport.connected = true;
            uint32_t epoch = s_epoch;
            portEXIT_CRITICAL(&s_state_lock);
            reset_message();
            s_binary = false;
#ifdef CONFIG_TOUCH_VOICE
            touch_capture_connection(true, epoch);
#else
    (void)epoch;
#endif
            notify_state(UI_TRANSPORT_CONNECTED);
            break;
        case WEBSOCKET_EVENT_DATA:
            if (event_data != NULL && ui_transport_is_connected()) {
                const esp_websocket_event_data_t *event = event_data;
                if (event->op_code == 2) s_binary = true;
                else if (event->op_code == 1) s_binary = false;
                /* Response PCM is deliberately drained, with no buffering. */
                if (!s_binary && (event->op_code == 1 || event->op_code == 0)) handle_text_frame(event, connection_epoch());
            }
            break;
        case WEBSOCKET_EVENT_ERROR:
            ui_transport_invalidate();
            break;
        case WEBSOCKET_EVENT_DISCONNECTED:
        case WEBSOCKET_EVENT_CLOSED:
            ui_transport_invalidate();
            break;
        case WEBSOCKET_EVENT_FINISH:
            ui_transport_invalidate();
            break;
        default:
            break;
    }
}

static esp_err_t start_locked(const ui_transport_config_t *config)
{
    if (config == NULL || config->uri == NULL || config->uri[0] == '\0' || config->on_snapshot == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_transport.client != NULL) return ESP_ERR_INVALID_STATE;

    if (!s_send_mutex) s_send_mutex = xSemaphoreCreateMutex();
    if (!s_send_mutex) return ESP_ERR_NO_MEM;
    portENTER_CRITICAL(&s_state_lock);
    memset(&s_transport, 0, sizeof(s_transport));
    portEXIT_CRITICAL(&s_state_lock);
    s_transport.config = *config;
    portENTER_CRITICAL(&s_state_lock);
    s_restart = false;
    s_transport.stopping = false;
    portEXIT_CRITICAL(&s_state_lock);
    notify_state(UI_TRANSPORT_CONNECTING);

    esp_websocket_client_config_t websocket_config = {
        .uri = config->uri,
        .user_context = &s_transport,
        .buffer_size = UI_TRANSPORT_BUFFER_SIZE,
        .disable_auto_reconnect = true,
        .enable_close_reconnect = false,
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
        s_transport.client, WEBSOCKET_EVENT_ANY, websocket_event_handler, s_transport.client);
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

esp_err_t ui_transport_start(const ui_transport_config_t *config)
{
    if (!s_send_mutex) s_send_mutex = xSemaphoreCreateMutex();
    if (!s_send_mutex) return ESP_ERR_NO_MEM;
    xSemaphoreTake(s_send_mutex, portMAX_DELAY);
    esp_err_t result = start_locked(config);
    xSemaphoreGive(s_send_mutex);
    return result;
}

esp_err_t ui_transport_stop(void)
{
    if (s_transport.client == NULL) {
        notify_state(UI_TRANSPORT_STOPPED);
        return ESP_OK;
    }
    xSemaphoreTake(s_send_mutex, portMAX_DELAY);
    portENTER_CRITICAL(&s_state_lock);
    s_transport.stopping = true;
    portEXIT_CRITICAL(&s_state_lock);
    ui_transport_invalidate();
    esp_err_t err = esp_websocket_client_stop(s_transport.client);
    esp_err_t destroy_err = esp_websocket_client_destroy(s_transport.client);
    s_transport.client = NULL;
    reset_message();
    notify_state(UI_TRANSPORT_STOPPED);
    xSemaphoreGive(s_send_mutex);
    return err != ESP_OK ? err : destroy_err;
}

bool ui_transport_is_connected(void)
{
    portENTER_CRITICAL(&s_state_lock);
    bool value = s_transport.connected;
    portEXIT_CRITICAL(&s_state_lock);
    return value;
}

esp_err_t ui_transport_send_action(
    const char *action_id,
    const char *option_id,
    const char *operation,
    const char *object_id,
    const char *freshness
)
{
    if (action_id == NULL || action_id[0] == '\0' || option_id == NULL || option_id[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }
    uint32_t epoch = connection_epoch();
    if (!connection_matches(epoch)) return ESP_ERR_INVALID_STATE;

    cJSON *action = cJSON_CreateObject();
    bool typed = operation != NULL;
    bool valid = action != NULL &&
        cJSON_AddStringToObject(action, "type", "action") != NULL &&
        cJSON_AddNumberToObject(action, "schema", 1) != NULL &&
        cJSON_AddStringToObject(action, "action_id", action_id) != NULL;
    if (typed) {
        valid = valid &&
            (strcmp(operation, "choose") == 0 || strcmp(operation, "explore") == 0) &&
            object_id != NULL && object_id[0] != '\0' &&
            freshness != NULL && freshness[0] != '\0' &&
            cJSON_AddStringToObject(action, "operation", operation) != NULL &&
            cJSON_AddStringToObject(action, "option_id", option_id) != NULL &&
            cJSON_AddStringToObject(action, "object_id", object_id) != NULL &&
            cJSON_AddStringToObject(action, "freshness", freshness) != NULL;
    } else {
        valid = valid &&
            object_id == NULL && freshness == NULL &&
            cJSON_AddStringToObject(action, "choice", option_id) != NULL;
    }
    if (!valid) {
        cJSON_Delete(action);
        return typed ? ESP_ERR_INVALID_ARG : ESP_ERR_NO_MEM;
    }

    char *payload = cJSON_PrintUnformatted(action);
    cJSON_Delete(action);
    if (payload == NULL) return ESP_ERR_NO_MEM;

    esp_err_t result = ui_transport_send_text_epoch(payload, epoch);
    cJSON_free(payload);
    return result;
}

static esp_err_t ordered_send(const void *data, size_t n, bool binary, uint32_t epoch)
{
    if (!s_send_mutex || xSemaphoreTake(s_send_mutex, pdMS_TO_TICKS(100)) != pdTRUE) return ESP_FAIL;
    int sent = -1;
    if (connection_matches(epoch) && s_transport.client) {
        sent = binary ? esp_websocket_client_send_bin(s_transport.client, data, n, pdMS_TO_TICKS(100))
                      : esp_websocket_client_send_text(s_transport.client, data, n, pdMS_TO_TICKS(100));
    }
    xSemaphoreGive(s_send_mutex);
    return sent == (int)n ? ESP_OK : ESP_FAIL;
}
esp_err_t ui_transport_send_text(const char *text)
{
    return text ? ordered_send(text, strlen(text), false, connection_epoch()) : ESP_ERR_INVALID_ARG;
}
esp_err_t ui_transport_send_pcm(const void *pcm, size_t size)
{
    if (!pcm || !size || size > 4096 || (size & 1)) return ESP_ERR_INVALID_ARG;
    return ordered_send(pcm, size, true, connection_epoch());
}
esp_err_t ui_transport_send_text_epoch(const char *text, uint32_t epoch)
{
    return text ? ordered_send(text, strlen(text), false, epoch) : ESP_ERR_INVALID_ARG;
}
esp_err_t ui_transport_send_pcm_epoch(const void *pcm, size_t size, uint32_t epoch)
{
    if (!pcm || !size || size > 4096 || (size & 1)) return ESP_ERR_INVALID_ARG;
    return ordered_send(pcm, size, true, epoch);
}
void ui_transport_invalidate_epoch(uint32_t expected)
{
    portENTER_CRITICAL(&s_state_lock);
    if (expected != s_epoch) { portEXIT_CRITICAL(&s_state_lock); return; }
    s_transport.connected = false;
    s_restart = true;
    uint32_t epoch = ++s_epoch;
    portEXIT_CRITICAL(&s_state_lock);
#ifdef CONFIG_TOUCH_VOICE
    touch_capture_connection(false, epoch);
#else
    (void)epoch;
#endif
    notify_state(UI_TRANSPORT_ERROR);
}
void ui_transport_invalidate(void) { ui_transport_invalidate_epoch(connection_epoch()); }
bool ui_transport_needs_restart(void) {
    portENTER_CRITICAL(&s_state_lock);
    bool value = s_restart;
    portEXIT_CRITICAL(&s_state_lock);
    return value;
}
