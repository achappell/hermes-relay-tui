#include "network.c"
char test_ssid[80],test_password[80];
const char *IP_EVENT="IP", *WIFI_EVENT="WIFI";
static wifi_config_t applied;
static int connects, nvs_error, netif_calls;
static uint64_t clock_ms;
int nvs_flash_init(void) {return nvs_error;}
int esp_netif_init(void) {netif_calls++;return 0;}
int esp_event_loop_create_default(void) {return 0;}
void *esp_netif_create_default_wifi_sta(void) {return (void *)1;}
int esp_wifi_init(const wifi_init_config_t *c) {(void)c;return 0;}
int esp_event_handler_register(esp_event_base_t b,int id,void (*f)(void *,esp_event_base_t,int32_t,void *),void *a) {if(b==IP_EVENT)assert(id==ESP_EVENT_ANY_ID);(void)f;(void)a;return 0;}
int esp_wifi_set_storage(int v) {assert(v==WIFI_STORAGE_RAM);return 0;}
int esp_wifi_set_mode(int v) {(void)v;return 0;}
int esp_wifi_set_config(int v,const wifi_config_t *c) {(void)v;applied=*c;return 0;}
int esp_wifi_start(void) {event(NULL,WIFI_EVENT,WIFI_EVENT_STA_START,NULL);return 0;}
int esp_wifi_connect(void) {connects++;return -1;}
int64_t esp_timer_get_time(void) {return clock_ms*1000;}
int main(void) {
 memset(test_ssid,'s',32);memset(test_password,'a',64);
 nvs_error=ESP_ERR_NVS_NO_FREE_PAGES;assert(network_start()==nvs_error && !netif_calls);
 nvs_error=ESP_ERR_NVS_NEW_VERSION_FOUND;assert(network_start()==nvs_error && !netif_calls);
 nvs_error=0;assert(network_start()==ESP_OK && netif_calls==1);
 assert(!memcmp(applied.sta.ssid,test_ssid,32) && !memcmp(applied.sta.password,test_password,64));
 network_poll();assert(connects==1);
 for(int i=0;i<10;i++){clock_ms=100*i;network_poll();}assert(connects==1);
 clock_ms=1000;network_poll();assert(connects==2);clock_ms=2999;network_poll();assert(connects==2);
 clock_ms=3000;network_poll();assert(connects==3);
 event(NULL,IP_EVENT,IP_EVENT_STA_GOT_IP,NULL);network_poll();assert(network_ready());
 event(NULL,IP_EVENT,IP_EVENT_STA_LOST_IP,NULL);assert(!network_ready());
 event(NULL,IP_EVENT,IP_EVENT_STA_GOT_IP,NULL);assert(network_ready());
 event(NULL,WIFI_EVENT,WIFI_EVENT_STA_DISCONNECTED,NULL);network_poll();assert(connects==4);
 test_ssid[32]='s';assert(network_start()==ESP_ERR_INVALID_STATE);test_ssid[32]=0;
 test_password[64]='a';assert(network_start()==ESP_ERR_INVALID_STATE);test_password[64]=0;
 test_ssid[0]=0;assert(network_start()==ESP_ERR_INVALID_STATE);
 return 0;
}
