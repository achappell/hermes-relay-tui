#include "ui_transport.c"
static bool locked, replace_on_take;
static unsigned serial, sends, controls, snapshots;
static uint32_t published_epoch;
static bool published_connected;
SemaphoreHandle_t xSemaphoreCreateMutex(void) {return (void *)1;}
int xSemaphoreTake(SemaphoreHandle_t m,int timeout) {
 (void)m;(void)timeout;assert(!locked);
 if(replace_on_take) {
  replace_on_take=false;ui_transport_invalidate();
  s_transport.client=(void *)(uintptr_t)++serial;s_restart=false;
  websocket_event_handler(s_transport.client,NULL,WEBSOCKET_EVENT_CONNECTED,NULL);
 }
 locked=true;return pdTRUE;
}
int xSemaphoreGive(SemaphoreHandle_t m) {(void)m;assert(locked);locked=false;return pdTRUE;}
esp_websocket_client_handle_t esp_websocket_client_init(const esp_websocket_client_config_t *c) {assert(locked && c->disable_auto_reconnect);return (void *)(uintptr_t)++serial;}
int esp_websocket_register_events(esp_websocket_client_handle_t c,int id,void (*f)(void *,esp_event_base_t,int32_t,void *),void *arg) {(void)id;assert(c==arg && f==websocket_event_handler);return 0;}
int esp_websocket_client_start(esp_websocket_client_handle_t c) {websocket_event_handler(c,NULL,WEBSOCKET_EVENT_CONNECTED,NULL);return 0;}
int esp_websocket_client_stop(esp_websocket_client_handle_t c) {assert(locked);websocket_event_handler(c,NULL,WEBSOCKET_EVENT_DISCONNECTED,NULL);return 0;}
int esp_websocket_client_destroy(esp_websocket_client_handle_t c) {(void)c;assert(locked);return 0;}
int esp_websocket_client_send_text(esp_websocket_client_handle_t c,const char *s,int n,int timeout) {(void)s;(void)timeout;assert(locked && c==s_transport.client);sends++;return n;}
int esp_websocket_client_send_bin(esp_websocket_client_handle_t c,const char *s,int n,int timeout) {return esp_websocket_client_send_text(c,s,n,timeout);}
void touch_capture_connection(bool connected,uint32_t epoch) {published_connected=connected;published_epoch=epoch;}
void touch_capture_control(const char *json,uint32_t epoch) {assert(json && epoch==published_epoch);controls++;}
bool ui_snapshot_from_json(const char *json,ui_snapshot_t *snapshot) {(void)json;memset(snapshot,0,sizeof(*snapshot));return true;}
static void snapshot(const ui_snapshot_t *s,void *u) {(void)s;(void)u;snapshots++;}
static void expect_bad_frame(const ui_transport_config_t *cfg,esp_websocket_event_data_t *e) {
 if(!ui_transport_is_connected()){assert(ui_transport_stop()==ESP_OK);assert(ui_transport_start(cfg)==ESP_OK);}
 websocket_event_handler(s_transport.client,NULL,WEBSOCKET_EVENT_DATA,e);
#ifdef CONFIG_TOUCH_VOICE
 assert(!ui_transport_is_connected() && ui_transport_needs_restart());
#else
 assert(ui_transport_is_connected());
#endif
}
static void framing_cases(const ui_transport_config_t *cfg) {
 char json[6000];const char *prefix="{\"type\":\"snapshot\",\"padding\":\"";size_t prefix_len=strlen(prefix);
 memcpy(json,prefix,prefix_len);memset(json+prefix_len,'x',5000-prefix_len);memcpy(json+5000,"\"}",3);
 unsigned before=snapshots;
 esp_websocket_event_data_t e={.data_ptr=json,.data_len=4096,.payload_len=5002,.op_code=1,.fin=true};
 websocket_event_handler(s_transport.client,NULL,WEBSOCKET_EVENT_DATA,&e);
 assert(ui_transport_is_connected() && snapshots==before);
 e.data_ptr=json+4096;e.data_len=5002-4096;e.payload_offset=4096;
 websocket_event_handler(s_transport.client,NULL,WEBSOCKET_EVENT_DATA,&e);assert(snapshots==before+1);
 e=(esp_websocket_event_data_t){.data_ptr="x",.data_len=1,.payload_len=UI_TRANSPORT_MESSAGE_MAX,.op_code=1,.fin=true};expect_bad_frame(cfg,&e);
 e.payload_len=1;e.payload_offset=-1;expect_bad_frame(cfg,&e);
 e.payload_offset=0;e.data_len=2;expect_bad_frame(cfg,&e);
 const char *bad_json[]={"{", "{}", "{\"type\":7}"};
 for(unsigned i=0;i<3;i++) {
  e=(esp_websocket_event_data_t){.data_ptr=bad_json[i],.data_len=(int)strlen(bad_json[i]),.payload_len=(int)strlen(bad_json[i]),.op_code=1,.fin=true};
  expect_bad_frame(cfg,&e);
 }
 if(!ui_transport_is_connected()){assert(ui_transport_stop()==ESP_OK);assert(ui_transport_start(cfg)==ESP_OK);}
 e=(esp_websocket_event_data_t){.data_ptr="{",.data_len=1,.payload_len=5,.op_code=1,.fin=true};
 websocket_event_handler(s_transport.client,NULL,WEBSOCKET_EVENT_DATA,&e);assert(ui_transport_is_connected());
 e.payload_offset=2;expect_bad_frame(cfg,&e); /* skipped chunk cannot lose terminal silently */
}
int main(void) {
 ui_transport_config_t cfg={.uri="ws://test/state",.on_snapshot=snapshot};
 assert(ui_transport_start(&cfg)==ESP_OK && !locked && ui_transport_is_connected());
 uint32_t first=connection_epoch();
 assert(ui_transport_send_text_epoch("{}",first)==ESP_OK && sends==1);
 replace_on_take=true;assert(ui_transport_send_text_epoch("{}",first)!=ESP_OK && sends==1);
 assert(connection_epoch()!=first);
 replace_on_take=true;assert(ui_transport_send_action("action","choice",NULL,NULL,NULL)!=ESP_OK && sends==1);
 assert(ui_transport_send_action("action","choice",NULL,NULL,NULL)==ESP_OK && sends==2);
 uint32_t current=connection_epoch();ui_transport_invalidate_epoch(first);assert(ui_transport_is_connected() && connection_epoch()==current);
 websocket_event_handler((void *)1,NULL,WEBSOCKET_EVENT_DISCONNECTED,NULL);assert(ui_transport_is_connected());
 const char *control="{\"schema\":1,\"type\":\"audio_start\",\"turn_id\":\"t\"}";
 esp_websocket_event_data_t e={.data_ptr=control,.data_len=(int)strlen(control),.payload_len=(int)strlen(control),.op_code=1,.fin=true};
 websocket_event_handler(s_transport.client,NULL,WEBSOCKET_EVENT_DATA,&e);
#ifdef CONFIG_TOUCH_VOICE
 assert(controls==1 && !snapshots);
#else
 assert(!controls && snapshots==1);
#endif
 e.op_code=2;e.data_ptr="audio";e.data_len=e.payload_len=5;unsigned before=snapshots;websocket_event_handler(s_transport.client,NULL,WEBSOCKET_EVENT_DATA,&e);assert(snapshots==before);
 framing_cases(&cfg);
 assert(ui_transport_stop()==ESP_OK && !locked && !published_connected);
 assert(ui_transport_send_pcm_epoch("xx",2,current)!=ESP_OK && sends==2);
 return 0;
}
