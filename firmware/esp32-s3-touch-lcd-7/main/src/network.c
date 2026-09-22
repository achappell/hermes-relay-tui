#include "network.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "sdkconfig.h"
#include <string.h>
#include <stdatomic.h>
static atomic_bool ready, connect_requested;
static void event(void *arg, esp_event_base_t base, int32_t id, void *data) {
  (void)arg;
  (void)data;
  if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
    ready = true;
    connect_requested = false;
  }
  else if (base == IP_EVENT && id == IP_EVENT_STA_LOST_IP) {
    ready = false;
  }
  else if (base == WIFI_EVENT &&
           (id == WIFI_EVENT_STA_START || id == WIFI_EVENT_STA_DISCONNECTED)) {
    ready = false;
    connect_requested = true;
  }
}
void network_poll(void) {
  /* Only the network task owns the retry clock; callbacks publish flags. */
  static uint64_t retry_at;
  static uint32_t retry_ms = 1000;
  if (ready) { retry_ms = 1000; retry_at = 0; return; }
  uint64_t now = esp_timer_get_time() / 1000;
  if (connect_requested && now >= retry_at) {
    connect_requested = false;
    if (esp_wifi_connect() != ESP_OK) connect_requested = true;
    retry_at = now + retry_ms;
    retry_ms = retry_ms >= 15000 ? 30000 : retry_ms * 2;
  }
}
bool network_ready(void) { return ready; }
esp_err_t network_start(void) {
  size_t ssid_len = strlen(CONFIG_TOUCH_WIFI_SSID);
  size_t key_len = strlen(CONFIG_TOUCH_WIFI_PASSWORD);
  if (!ssid_len || ssid_len > sizeof(((wifi_config_t *)0)->sta.ssid) ||
      key_len > sizeof(((wifi_config_t *)0)->sta.password))
    return ESP_ERR_INVALID_STATE;
  esp_err_t nvs_error = nvs_flash_init();
  if (nvs_error != ESP_OK) return nvs_error;
  ESP_ERROR_CHECK(esp_netif_init());
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();
  wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_wifi_init(&init));
  ESP_ERROR_CHECK(
      esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, event, NULL));
  ESP_ERROR_CHECK(
      esp_event_handler_register(IP_EVENT, ESP_EVENT_ANY_ID, event, NULL));
  wifi_config_t config = {0};
  memcpy(config.sta.ssid, CONFIG_TOUCH_WIFI_SSID, ssid_len);
  memcpy(config.sta.password, CONFIG_TOUCH_WIFI_PASSWORD, key_len);
  ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &config));
  return esp_wifi_start();
}
