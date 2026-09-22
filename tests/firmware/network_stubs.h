#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_INVALID_STATE 2
#define ESP_ERROR_CHECK(x) assert((x)==0)
typedef const char *esp_event_base_t;
extern const char *IP_EVENT, *WIFI_EVENT;
#define IP_EVENT_STA_GOT_IP 1
#define IP_EVENT_STA_LOST_IP 4
#define ESP_ERR_NVS_NO_FREE_PAGES 100
#define ESP_ERR_NVS_NEW_VERSION_FOUND 101
#define WIFI_EVENT_STA_START 2
#define WIFI_EVENT_STA_DISCONNECTED 3
#define ESP_EVENT_ANY_ID -1
#define WIFI_STORAGE_RAM 1
#define WIFI_MODE_STA 1
#define WIFI_IF_STA 1
typedef struct {int dummy;} wifi_init_config_t;
#define WIFI_INIT_CONFIG_DEFAULT() ((wifi_init_config_t){0})
typedef struct {struct {uint8_t ssid[32],password[64];} sta;} wifi_config_t;
int nvs_flash_init(void);
int esp_netif_init(void);
int esp_event_loop_create_default(void);
void *esp_netif_create_default_wifi_sta(void);
int esp_wifi_init(const wifi_init_config_t *);
int esp_event_handler_register(esp_event_base_t,int,void (*)(void *,esp_event_base_t,int32_t,void *),void *);
int esp_wifi_set_storage(int);
int esp_wifi_set_mode(int);
int esp_wifi_set_config(int,const wifi_config_t *);
int esp_wifi_start(void);
int esp_wifi_connect(void);
int64_t esp_timer_get_time(void);
extern char test_ssid[80], test_password[80];
#define CONFIG_TOUCH_WIFI_SSID test_ssid
#define CONFIG_TOUCH_WIFI_PASSWORD test_password
