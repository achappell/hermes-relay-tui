#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <assert.h>
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NO_MEM 1
#define ESP_ERR_INVALID_ARG 2
#define ESP_ERR_INVALID_STATE 3
#define ESP_LOGW(tag, ...) ((void)(tag))
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(p) ((void)(p))
#define portEXIT_CRITICAL(p) ((void)(p))
typedef void *SemaphoreHandle_t;
#define pdTRUE 1
#define pdMS_TO_TICKS(x) (x)
#define portMAX_DELAY -1
SemaphoreHandle_t xSemaphoreCreateMutex(void);
int xSemaphoreTake(SemaphoreHandle_t,int);
int xSemaphoreGive(SemaphoreHandle_t);
typedef void *esp_websocket_client_handle_t;
typedef const char *esp_event_base_t;
typedef enum {WEBSOCKET_EVENT_BEGIN,WEBSOCKET_EVENT_CONNECTED,WEBSOCKET_EVENT_DATA,WEBSOCKET_EVENT_ERROR,WEBSOCKET_EVENT_DISCONNECTED,WEBSOCKET_EVENT_CLOSED,WEBSOCKET_EVENT_FINISH} esp_websocket_event_id_t;
#define WEBSOCKET_EVENT_ANY -1
typedef struct {const char *uri;void *user_context;int buffer_size;bool disable_auto_reconnect,enable_close_reconnect;int reconnect_timeout_ms;} esp_websocket_client_config_t;
typedef struct {const char *data_ptr;int data_len,payload_len,payload_offset,op_code;bool fin;} esp_websocket_event_data_t;
esp_websocket_client_handle_t esp_websocket_client_init(const esp_websocket_client_config_t *);
int esp_websocket_register_events(esp_websocket_client_handle_t,int,void (*)(void *,esp_event_base_t,int32_t,void *),void *);
int esp_websocket_client_start(esp_websocket_client_handle_t);
int esp_websocket_client_stop(esp_websocket_client_handle_t);
int esp_websocket_client_destroy(esp_websocket_client_handle_t);
int esp_websocket_client_send_text(esp_websocket_client_handle_t,const char *,int,int);
int esp_websocket_client_send_bin(esp_websocket_client_handle_t,const char *,int,int);
