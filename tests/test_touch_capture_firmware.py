"""Portable UART vectors and the actual S3 ordered-sender state machine."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / 'shared/touch_audio'


def compile_run(tmp_path, source, extra=(), includes=()):
    harness = tmp_path / 'harness.c'
    harness.write_text(source)
    binary = tmp_path / 'harness'
    subprocess.run([shutil.which('cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-I', str(SHARED), *[a for p in includes for a in ('-I', str(p))],
                    str(harness), str(SHARED/'capture_protocol.c'),
                    str(SHARED/'capture_state.c'), *map(str, extra), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)


def test_uart_vectors_and_capture_lease(tmp_path):
    compile_run(tmp_path, r'''
#include "capture_state.h"
#include <assert.h>
#include <string.h>
/* COBS pack independently constructed decoded bytes, including invalid headers. */
static size_t pack(const uint8_t *raw,size_t length,uint8_t *wire) {
 size_t out=1,code_at=0;uint8_t code=1;
 for(size_t i=0;i<length;i++) {
  if(raw[i]==0) {wire[code_at]=code;code_at=out++;code=1;}
  else {wire[out++]=raw[i];if(++code==255){wire[code_at]=code;code_at=out++;code=1;}}
 }
 wire[code_at]=code;wire[out++]=0;return out;
}
int main(void) {
 uint8_t raw[22]={1,TC_PCM,2,0,42,0,0,0,1,0,0,0};uint8_t invalid[TC_WIRE_MAX];tc_frame_t parsed;
 tc_put_u32(raw+18,tc_crc32(raw,18));size_t malformed=pack(raw,sizeof(raw),invalid);assert(tc_decode(invalid,malformed-1,&parsed));
 raw[0]=2;tc_put_u32(raw+18,tc_crc32(raw,18));malformed=pack(raw,sizeof(raw),invalid);assert(!tc_decode(invalid,malformed-1,&parsed));
 raw[0]=1;raw[2]=4;tc_put_u32(raw+18,tc_crc32(raw,18));malformed=pack(raw,sizeof(raw),invalid);assert(!tc_decode(invalid,malformed-1,&parsed));
 raw[2]=2;raw[4]=0;tc_put_u32(raw+18,tc_crc32(raw,18));malformed=pack(raw,sizeof(raw),invalid);assert(!tc_decode(invalid,malformed-1,&parsed));
 assert(tc_crc32((const uint8_t *)"123456789",9)==0xcbf43926u);
 tc_frame_t f={.type=TC_PCM,.generation=42,.capture=1,.length=1024},out;
 for(unsigned i=0;i<1024;i++) f.payload[i]=(uint8_t)i;
 uint8_t wire[TC_WIRE_MAX];size_t n=tc_encode(&f,wire,sizeof(wire));assert(n<=1050);
 for(size_t split=0;split<n;split++) {
  tc_parser_t parser={0};int frames=0;
  for(size_t i=0;i<split;i++) frames+=tc_feed(&parser,wire[i],&out)==1;
  for(size_t i=split;i<n;i++) frames+=tc_feed(&parser,wire[i],&out)==1;
  assert(frames==1 && out.length==1024 && !memcmp(out.payload,f.payload,1024));
  for(size_t i=0;i<n;i++) frames+=tc_feed(&parser,wire[i],&out)==1;
  assert(frames==2);
 }
 wire[10]^=1;assert(!tc_decode(wire,n-1,&out));wire[10]^=1;
 tc_parser_t parser={0};int bad=0;
 for(size_t i=0;i<n-1;i++) tc_feed(&parser,wire[i],&out);
 for(size_t i=0;i<n;i++) bad|=tc_feed(&parser,wire[i],&out)<0;
 assert(bad);int frames=0;for(size_t i=0;i<n;i++) frames+=tc_feed(&parser,wire[i],&out)==1;assert(frames==1);
 f.length=1025;assert(!tc_encode(&f,wire,sizeof(wire)));f.length=3;assert(!tc_encode(&f,wire,sizeof(wire)));
 uint8_t pcm[2];uint32_t vectors[]={0,0x7fffff00,0x80000000,0xffffff00,0x12345600};
 uint16_t expected[]={0,32767,32768,65535,0x1234};
 for(unsigned i=0;i<5;i++) {tc_pcm16(vectors[i],pcm);assert((pcm[0]|(pcm[1]<<8))==expected[i]);}
 tc_state_t s={0};f=(tc_frame_t){.type=TC_START,.generation=42,.capture=1};assert(tc_command(&s,&f,0)==0);
 f.type=TC_HELLO;f.capture=0;assert(tc_command(&s,&f,0)==1 && s.phase==TC_IDLE);assert(tc_command(&s,&f,1)==1);
 f.type=TC_START;f.capture=1;assert(tc_command(&s,&f,10)==1);assert(tc_command(&s,&f,11)==0);tc_frame_t hello={.type=TC_HELLO,.generation=42};assert(tc_command(&s,&hello,12)==0 && s.phase==TC_STARTING);hello.generation=41;hello.type=TC_ABORT;hello.capture=1;assert(tc_command(&s,&hello,12)==0 && s.phase==TC_STARTING);
 assert(tc_tick(&s,1010)==-1);tc_abort(&s);assert(tc_command(&s,&f,1011)==0);
 f.capture=2;assert(tc_command(&s,&f,2000)==1);assert(tc_started(&s,2256));
 for(unsigned i=0;i<468;i++) assert(tc_accept_pcm(&s,1024));assert(tc_accept_pcm(&s,768));assert(s.bytes==480000);assert(!tc_accept_pcm(&s,2));
 assert(tc_tick(&s,2257)==1);tc_ended(&s);f.type=TC_END;assert(tc_command(&s,&f,2258)==2);
 f.type=TC_START;assert(tc_command(&s,&f,2259)==0);f.capture=3;assert(tc_command(&s,&f,3000)==1);assert(tc_started(&s,3256));
 f.type=TC_KEEPALIVE;assert(tc_command(&s,&f,18255)==1);assert(tc_tick(&s,18256)==1);assert(tc_tick(&s,19255)==-1);
 return 0;
}
''')


def test_s3_actual_sender_readiness_order_cancel_and_terminal_fences(tmp_path):
    cjson = ROOT/'tests/vendor/cjson'
    (tmp_path/'freertos').mkdir()
    (tmp_path/'esp_err.h').write_text('#pragma once\ntypedef int esp_err_t;\n#define ESP_OK 0\n#define ESP_FAIL -1\n#define ESP_ERR_NO_MEM 1\n')
    (tmp_path/'esp_timer.h').write_text('#include <stdint.h>\nint64_t esp_timer_get_time(void);\n')
    (tmp_path/'esp_random.h').write_text('#include <stdint.h>\nuint32_t esp_random(void);\n')
    (tmp_path/'freertos/FreeRTOS.h').write_text('''#pragma once
#include <stddef.h>
#include <stdint.h>
typedef void *QueueHandle_t;
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(p) ((void)(p))
#define portEXIT_CRITICAL(p) ((void)(p))
#define pdTRUE 1
#define pdPASS 1
#define pdMS_TO_TICKS(x) (x)
''')
    (tmp_path/'freertos/queue.h').write_text('''#include "FreeRTOS.h"
QueueHandle_t xQueueCreate(int n, size_t size);
int xQueueSend(QueueHandle_t q,const void *data,int wait);
int xQueueReceive(QueueHandle_t q,void *data,int wait);
void xQueueReset(QueueHandle_t q);
''')
    (tmp_path/'freertos/task.h').write_text('''#include "FreeRTOS.h"
int xTaskCreate(void (*fn)(void *),const char *name,int stack,void *arg,int priority,void *handle);
void vTaskDelay(int ticks);
''')
    firmware = ROOT/'firmware/esp32-s3-touch-lcd-7/main'
    compile_run(tmp_path, r'''
#include <assert.h>
#include <stdlib.h>
#include "capture_state.h"
#include "touch_capture.c"
static uint64_t clock_ms;
static int uart_types[4096],uart_count,host_count,invalidated;
static char host[4096][256];
static tc_state_t peer;
static bool coupled, produce_pcm, bad_uart, disconnect_send;
static uint64_t send_delay;
static int resets, reads;
static tc_frame_t inbound[64]; static unsigned in_count;
static void incoming(tc_frame_t f) { assert(in_count<64);inbound[in_count++]=f; }
static unsigned char queued[16][sizeof(input_t)];static int qcount;
int64_t esp_timer_get_time(void) { return clock_ms*1000; }
uint32_t esp_random(void) { return 123; }
QueueHandle_t xQueueCreate(int n,size_t size) { assert(n==16 && size==sizeof(input_t));return (void *)1; }
int xQueueSend(QueueHandle_t q,const void *v,int wait) { (void)q;(void)wait;if(qcount==16) return 0;memcpy(queued[qcount++],v,sizeof(input_t));return 1; }
int xQueueReceive(QueueHandle_t q,void *v,int wait) { (void)q;(void)wait;if(!qcount) return 0;memcpy(v,queued[0],sizeof(input_t));memmove(queued,queued+1,(--qcount)*sizeof(input_t));return 1; }
void xQueueReset(QueueHandle_t q) { (void)q;qcount=0; }
int xTaskCreate(void (*f)(void *),const char *n,int s,void *a,int p,void *h) { (void)f;(void)n;(void)s;(void)a;(void)p;(void)h;return 1; }
void vTaskDelay(int t) { clock_ms+=t; }
esp_err_t touch_uart_init(void) { return ESP_OK; }
bool touch_uart_send(const tc_frame_t *f) { uart_types[uart_count++]=f->type;
 if(coupled) {
   int result=tc_command(&peer,f,clock_ms); assert(result>=0);
   if(result && f->type==TC_HELLO) incoming((tc_frame_t){.type=TC_READY,.generation=f->generation});
 }
 return true; }
int touch_uart_read(tc_frame_t *f) {
 reads++;
 if(bad_uart) { bad_uart=false; return -1; }
 if(in_count) { *f=inbound[0]; memmove(inbound,inbound+1,(--in_count)*sizeof(*f));return 1; }
 if(produce_pcm && peer.phase==TC_CAPTURING) {
  *f=(tc_frame_t){.type=TC_PCM,.generation=peer.generation,.capture=peer.capture,.sequence=peer.sequence,.length=2};
  assert(tc_accept_pcm(&peer,2));return 1;
 }
 return 0;
}
void touch_uart_rebind(bool r) { in_count=0;if(r) resets++; }
esp_err_t ui_transport_send_text_epoch(const char *s,uint32_t expected) { assert(expected==connection_epoch);strcpy(host[host_count++],s);clock_ms+=send_delay;
 if(disconnect_send && strstr(s,"mic_capture_started")) { disconnect_send=false;touch_capture_connection(false,connection_epoch+1); }
 return ESP_OK; }
esp_err_t ui_transport_send_pcm_epoch(const void *p,size_t n,uint32_t expected) { (void)p;assert(expected==connection_epoch);assert(n==2);strcpy(host[host_count++],"PCM");clock_ms+=send_delay;return ESP_OK; }
void ui_transport_invalidate_epoch(uint32_t expected) { assert(expected==epoch); invalidated++;connected=false;connection_epoch++; }
static void setup(void) { epoch=connection_epoch=7;generation=5;capture=0;connected=linked=true;phase=TOUCH_IDLE;capture_id[0]=0;host_count=uart_count=invalidated=0;clock_ms=0;overflow=false;xQueueReset(queue);publish(); }
static void step(void) { int before=reads;touch_capture_worker_step();assert(reads-before<=1); }
static void worker_setup(void) {
 setup();coupled=true;produce_pcm=bad_uart=disconnect_send=false;send_delay=0;resets=reads=0;in_count=0;peer=(tc_state_t){0};
 epoch=0;touch_capture_connection(true,7);step();assert(phase==TOUCH_IDLE && peer.phase==TC_IDLE);
 touch_capture_command(TOUCH_TALK);step();assert(phase==TOUCH_ADMISSION && peer.phase==TC_IDLE);
 char json[256];snprintf(json,sizeof(json),"{\"schema\":1,\"type\":\"mic_ready\",\"capture_id\":\"%s\",\"capture_terminal\":true}",capture_id);
 touch_capture_control(json,7);step();assert(phase==TOUCH_STARTING && peer.phase==TC_STARTING);
}
static void worker_started(void) {
 clock_ms+=256;assert(tc_started(&peer,clock_ms));
 incoming((tc_frame_t){.type=TC_STARTED,.generation=generation,.capture=capture});step();
 assert(phase==TOUCH_RECORDING);
}
static void worker_cases(void) {
 worker_setup();worker_started();produce_pcm=true;
 for(int i=0;i<200;i++) {clock_ms+=16;step();assert(tc_tick(&peer,clock_ms)==0);assert(phase==TOUCH_RECORDING);}
 assert(uart_count>12 && host_count>200); /* Multiple renewed one-second leases. */
 send_delay=100;
 for(int i=0;i<20;i++) {step();assert(tc_tick(&peer,clock_ms)==0);}
 touch_capture_command(TOUCH_CANCEL);step();assert(phase==TOUCH_ABORTING && peer.phase==TC_IDLE);
 assert(!strstr(host[host_count-1],"mic_end"));
 worker_setup();worker_started();produce_pcm=true;send_delay=300;step();assert(invalidated && phase==TOUCH_UNAVAILABLE);
 worker_setup();worker_started();bad_uart=true;step();assert(invalidated);
 worker_setup();for(int i=0;i<8;i++){clock_ms+=250;step();}assert(invalidated); /* startup deadline, lease serviced */
 worker_setup();worker_started();touch_capture_command(TOUCH_FINISH);step();
 for(int i=0;i<4;i++){clock_ms+=250;step();}assert(invalidated); /* drain deadline */
 worker_setup(); /* Cancel queued before the ready/started transition remains valid. */
 input_t cancel={.epoch=7,.capture=capture,.kind=3,.requested_phase=TOUCH_ADMISSION};enqueue(&cancel);step();assert(phase==TOUCH_ABORTING);
 worker_setup();worker_started();
 cancel=(input_t){.epoch=7,.capture=capture,.kind=3,.requested_phase=TOUCH_STARTING};enqueue(&cancel);step();assert(phase==TOUCH_ABORTING);
 worker_setup();worker_started();touch_capture_command(TOUCH_FINISH);touch_capture_command(TOUCH_CANCEL);step();step();assert(phase==TOUCH_DRAINING);
 worker_setup();disconnect_send=true;clock_ms+=256;assert(tc_started(&peer,clock_ms));incoming((tc_frame_t){.type=TC_STARTED,.generation=generation,.capture=capture});step();
 assert(touch_capture_phase()==TOUCH_UNAVAILABLE);step();assert(!capture_id[0]);
 touch_capture_connection(true,9);step();assert(phase==TOUCH_IDLE);int sent=host_count;step();assert(host_count==sent); /* No automatic replay. */
 touch_capture_connection(true,7);assert(connection_epoch==9); /* delayed publication */
 touch_capture_command(TOUCH_TALK);step();assert(phase==TOUCH_ADMISSION && capture==1);
 input_t grant={.epoch=9,.kind=10,.capability=true};strcpy(grant.id,capture_id);enqueue(&grant);step();assert(peer.phase==TC_STARTING); /* fresh generation despite repeated RNG value */
 worker_setup();touch_capture_control("{\"schema\":1,\"type\":\"mic_terminal\",\"outcome\":\"complete\"}",7);step();assert(invalidated);
 worker_setup();for(int i=0;i<17;i++) touch_capture_command(TOUCH_CANCEL);step();assert(invalidated);
 /* Lost initial HELLO retries recover boot without a reset; total timeout gets one reset. */
 setup();coupled=false;epoch=0;resets=0;touch_capture_connection(true,7);step();int hello=uart_count;
 for(int i=0;i<4;i++){clock_ms+=200;step();}assert(uart_count==hello+4 && resets==0);
 clock_ms=1000;step();assert(resets==1);clock_ms=2000;step();clock_ms=4000;step();assert(resets==1);
}
static int allocation_count, fail_allocation=-1;
static void *allocation(size_t size) { int index=allocation_count++;return index==fail_allocation?NULL:malloc(size); }
static void audio_setup(void) {
 setup();coupled=produce_pcm=bad_uart=false;send_delay=0;in_count=0;phase=TOUCH_WORKING;failed_audio[0]=0;
 touch_capture_control("{\"schema\":1,\"type\":\"audio_start\",\"turn_id\":\"turn\\\"one\"}",7);
}
static void audio_cases(void) {
 audio_setup();allocation_count=0;fail_allocation=-1;cJSON_Hooks hooks={.malloc_fn=allocation,.free_fn=free};cJSON_InitHooks(&hooks);
 step();int required=allocation_count;cJSON_InitHooks(NULL);
 assert(host_count==1 && !invalidated && required>4);
 cJSON *ack=cJSON_Parse(host[0]);assert(ack && cJSON_GetArraySize(ack)==4);
 assert(cJSON_GetObjectItem(ack,"schema")->valuedouble==1);
 assert(!strcmp(cJSON_GetObjectItem(ack,"type")->valuestring,"audio_playback_failed"));
 assert(!strcmp(cJSON_GetObjectItem(ack,"turn_id")->valuestring,"turn\"one"));
 assert(!strcmp(cJSON_GetObjectItem(ack,"reason")->valuestring,"unsupported"));cJSON_Delete(ack);
 touch_capture_control("{\"schema\":1,\"type\":\"audio_start\",\"turn_id\":\"turn\\\"one\"}",7);step();assert(host_count==1);
 touch_capture_control("{\"schema\":1,\"type\":\"audio_start\",\"turn_id\":\"second\"}",7);step();assert(host_count==2);
 for(int i=0;i<required;i++) {
  audio_setup();allocation_count=0;fail_allocation=i;cJSON_InitHooks(&hooks);step();cJSON_InitHooks(NULL);
  assert(invalidated && !host_count && !failed_audio[0]);
 }
 fail_allocation=-1;
}
static void talk(void) { input_t e={.epoch=7,.kind=1,.requested_phase=TOUCH_IDLE};input(&e);publish();assert(phase==TOUCH_ADMISSION);assert(uart_count==0); }
static void ready(void) { input_t e={.epoch=7,.kind=10,.capability=true};strcpy(e.id,capture_id);input(&e);assert(phase==TOUCH_STARTING && uart_types[0]==TC_START); }
static void terminal(const char *outcome) { input_t e={.epoch=7,.kind=12};strcpy(e.id,capture_id);strcpy(e.outcome,outcome);input(&e); }
int main(void) {
 assert(touch_capture_init()==ESP_OK);setup();talk();ready();
 tc_frame_t f={.generation=5,.capture=1,.type=TC_STARTED};uart_frame(&f);assert(phase==TOUCH_RECORDING);
 assert(strstr(host[0],"mic_start") && strstr(host[1],"mic_capture_started"));
 f.type=TC_PCM;f.length=2;uart_frame(&f);assert(!strcmp(host[2],"PCM"));
 publish();touch_capture_command(TOUCH_FINISH);touch_capture_command(TOUCH_CANCEL);
 input_t event;while(xQueueReceive(queue,&event,0)) input(&event);assert(phase==TOUCH_DRAINING);assert(uart_types[uart_count-1]==TC_END);
 f.type=TC_ENDED;f.sequence=1;f.length=4;tc_put_u32(f.payload,2);uart_frame(&f);assert(phase==TOUCH_WORKING);assert(strstr(host[3],"mic_end"));uart_frame(&f);assert(host_count==4);
 terminal("complete");assert(phase==TOUCH_IDLE);uart_frame(&f);assert(host_count==4);
 setup();talk();input_t reject={.epoch=7,.kind=10};strcpy(reject.id,capture_id);input(&reject);assert(invalidated && uart_count==1 && uart_types[0]==TC_ABORT);
 setup();talk();touch_capture_command(TOUCH_CANCEL);xQueueReceive(queue,&event,0);input(&event);assert(invalidated);ready; /* no late grant can open C6 */
 setup();talk();ready();terminal("no_turn");f=(tc_frame_t){.generation=5,.capture=1,.type=TC_STARTED};uart_frame(&f);assert(phase==TOUCH_IDLE && host_count==1);
 setup();talk();ready();f.type=TC_STARTED;uart_frame(&f);f.type=TC_PCM;f.length=2;f.sequence=1;uart_frame(&f);assert(invalidated && host_count==2);
 setup();talk();ready();f=(tc_frame_t){.generation=5,.capture=1,.type=TC_STARTED};uart_frame(&f);terminal("error");assert(invalidated);
 setup();for(int i=0;i<17;i++) touch_capture_command(TOUCH_TALK);assert(overflow && qcount==16);
 worker_cases();
 audio_cases();
 return 0;
}
'''.replace('ready; /* no late grant can open C6 */','/* no late grant can open C6 */'),
                extra=[cjson/'cJSON.c'], includes=[tmp_path,firmware/'include',firmware/'src',ROOT/'shared/display',cjson])


def test_c6_actual_dma_stop_drain_and_failure_orchestration(tmp_path):
    for directory in ('driver', 'freertos'):
        (tmp_path/directory).mkdir()
    for header in ('driver/gpio.h', 'driver/i2s_std.h', 'driver/uart.h',
                   'esp_timer.h', 'freertos/FreeRTOS.h', 'freertos/task.h', 'freertos/queue.h'):
        (tmp_path/header).write_text('#include "c6_stubs.h"\n')
    compile_run(tmp_path, (ROOT/'tests/firmware/c6_orchestration.c').read_text(),
                includes=[tmp_path, ROOT/'tests/firmware', ROOT/'firmware/esp32-c6-audio/main'])


@pytest.mark.parametrize("voice", [True, False])
def test_transport_actual_socket_lifetime_and_epoch_fences(tmp_path, voice):
    (tmp_path/'freertos').mkdir()
    for header in ('esp_err.h', 'esp_log.h', 'esp_websocket_client.h',
                   'freertos/FreeRTOS.h', 'freertos/task.h', 'freertos/semphr.h'):
        (tmp_path/header).write_text('#include "transport_stubs.h"\n')
    (tmp_path/'sdkconfig.h').write_text('#define CONFIG_TOUCH_VOICE 1\n' if voice else '')
    firmware = ROOT/'firmware/esp32-s3-touch-lcd-7/main'
    cjson = ROOT/'tests/vendor/cjson'
    compile_run(tmp_path, (ROOT/'tests/firmware/transport_lifetime.c').read_text(),
                extra=[cjson/'cJSON.c'], includes=[tmp_path, ROOT/'tests/firmware',
                firmware/'include', firmware/'src', ROOT/'shared/display', cjson])


def test_network_actual_full_capacity_configuration_and_backoff(tmp_path):
    for header in ('esp_err.h', 'esp_event.h', 'esp_netif.h', 'esp_wifi.h',
                   'esp_timer.h', 'nvs_flash.h', 'sdkconfig.h'):
        (tmp_path/header).write_text('#include "network_stubs.h"\n')
    firmware = ROOT/'firmware/esp32-s3-touch-lcd-7/main'
    compile_run(tmp_path, (ROOT/'tests/firmware/network_config.c').read_text(),
                includes=[tmp_path, ROOT/'tests/firmware', firmware/'include', firmware/'src'])


def test_actual_capture_ui_recovers_after_discarded_same_phase_command(tmp_path):
    (tmp_path/'driver').mkdir()
    for header in ('driver/gpio.h', 'driver/i2c.h'):
        (tmp_path/header).write_text('#pragma once\n')
    (tmp_path/'esp_err.h').write_text('typedef int esp_err_t;\n')
    (tmp_path/'sdkconfig.h').write_text('#define CONFIG_TOUCH_VOICE 1\n')
    (tmp_path/'lvgl.h').write_text('#include "lvgl_stubs.h"\n')
    firmware = ROOT/'firmware/esp32-s3-touch-lcd-7/main'
    compile_run(tmp_path, r'''#define ESP_PLATFORM 1
#include <assert.h>
#include "ui_display.c"
static int commands;
void touch_capture_command(touch_command_t command) {(void)command;commands++;}
const char *touch_capture_status(void) {return "Ready to talk";}
int main(void) {
 ui_display_capture_update(TOUCH_IDLE);
 assert(!(capture_buttons[0]->state & LV_STATE_DISABLED));
 lv_event_t event={.data=(void *)(uintptr_t)TOUCH_TALK};capture_click(&event);
 assert(commands==1 && (capture_buttons[0]->state & LV_STATE_DISABLED));
 /* The worker discards the old-epoch command; UI sees idle again. */
 ui_display_capture_update(TOUCH_IDLE);
 assert(!(capture_buttons[0]->state & LV_STATE_DISABLED));
 ui_display_capture_update(TOUCH_RECORDING);
 assert(!(capture_buttons[1]->state & LV_STATE_DISABLED) && !(capture_buttons[2]->state & LV_STATE_DISABLED));
 ui_display_capture_update(TOUCH_DRAINING);
 for(int i=0;i<3;i++)assert(capture_buttons[i]->state & LV_STATE_DISABLED);
 return 0;
}
''', extra=[firmware/'src/ui_snapshot.c', ROOT/'shared/display/display_rules.c'],
                includes=[tmp_path, ROOT/'tests/firmware', firmware/'include', firmware/'src', ROOT/'shared/display'])


def test_actual_uart_adapter_errors_flush_and_pcm_admission(tmp_path):
    for directory in ('driver', 'freertos'):
        (tmp_path/directory).mkdir()
    for header in ('esp_err.h', 'esp_timer.h', 'esp_random.h', 'driver/gpio.h',
                   'driver/i2c.h', 'driver/uart.h', 'freertos/FreeRTOS.h',
                   'freertos/queue.h', 'freertos/task.h'):
        (tmp_path/header).write_text('#include "uart_stubs.h"\n')
    firmware = ROOT/'firmware/esp32-s3-touch-lcd-7/main'
    cjson = ROOT/'tests/vendor/cjson'
    compile_run(tmp_path, (ROOT/'tests/firmware/uart_adapter.c').read_text(),
                extra=[cjson/'cJSON.c'], includes=[tmp_path, ROOT/'tests/firmware',
                firmware/'include', firmware/'src', ROOT/'shared/display', cjson])
