#include <stdlib.h>
#include "touch_capture.c"
#include "touch_uart.c"
/* Production parser/adapter and capture worker share real bytes/error events. */
typedef struct {unsigned count,limit;size_t size;unsigned char data[20][sizeof(input_t)];} queue_t;
static uint8_t incoming[TC_WIRE_MAX*4];static size_t incoming_size,incoming_pos;
static unsigned flushes, byte_reads, event_reads, host_pcm, invalidations, reset_levels, delay_ms;
static bool noise, endless_events, short_write;
static uint64_t clock_ms;
QueueHandle_t xQueueCreate(int n,size_t size) {queue_t *q=calloc(1,sizeof(*q));assert(n<=20 && size<=sizeof(input_t));q->limit=n;q->size=size;return q;}
int xQueueSend(QueueHandle_t handle,const void *data,int wait) {queue_t *q=handle;(void)wait;if(q->count==q->limit)return 0;memcpy(q->data[q->count++],data,q->size);return 1;}
int xQueueReceive(QueueHandle_t handle,void *data,int wait) {
 queue_t *q=handle;(void)wait;
 if(handle==events){event_reads++;if(endless_events){*(uart_event_t *)data=(uart_event_t){.type=UART_DATA};return 1;}}
 if(!q->count) {
  return 0;
 }
 memcpy(data,q->data[0],q->size);
 memmove(q->data,q->data+1,(--q->count)*sizeof(q->data[0]));
 return 1;
}
void xQueueReset(QueueHandle_t handle) {((queue_t *)handle)->count=0;}
int xTaskCreate(void (*f)(void *),const char *n,int s,void *a,int p,void *h) {(void)f;(void)n;(void)s;(void)a;(void)p;(void)h;return pdPASS;}
void vTaskDelay(int ms) {delay_ms+=ms;clock_ms+=ms;}
int64_t esp_timer_get_time(void) {return clock_ms*1000;}
uint32_t esp_random(void) {return 9;}
int gpio_config(const gpio_config_t *c) {assert(c->mode==GPIO_MODE_OUTPUT_OD);return 0;}
int gpio_set_level(int pin,int value) {assert(pin==BOARD_C6_RESET);reset_levels=(reset_levels<<1)|(unsigned)value;return 0;}
int uart_driver_install(int port,int rx,int tx,int n,QueueHandle_t *q,int flags) {assert(port==UART_NUM_1 && rx==16*1050 && tx==0 && n==20);(void)flags;*q=xQueueCreate(n,sizeof(uart_event_t));return 0;}
int uart_param_config(int p,const uart_config_t *c) {(void)p;assert(c->baud_rate==921600);return 0;}
int uart_set_pin(int p,int tx,int rx,int rts,int cts) {(void)p;assert(tx==43 && rx==44 && rts==-1 && cts==-1);return 0;}
int uart_write_bytes(int p,const void *wire,size_t n) {(void)p;tc_frame_t f;assert(tc_decode(wire,n-1,&f));return short_write?(int)n-1:(int)n;}
int uart_wait_tx_done(int p,int ticks) {(void)p;assert(ticks==40);return 0;}
int uart_flush_input(int p) {(void)p;flushes++;incoming_pos=incoming_size;return 0;}
int uart_read_bytes(int p,void *data,size_t n,int wait) {
 (void)p;(void)wait;assert(n==1);byte_reads++;
 if(noise){*(uint8_t *)data=1;return 1;}
 if(incoming_pos==incoming_size)return 0;
 *(uint8_t *)data=incoming[incoming_pos++];return 1;
}
esp_err_t ui_transport_send_text_epoch(const char *text,uint32_t expected) {(void)text;assert(expected==epoch);return 0;}
esp_err_t ui_transport_send_pcm_epoch(const void *pcm,size_t n,uint32_t expected) {assert(pcm && n==4 && expected==epoch);host_pcm++;return 0;}
void ui_transport_invalidate_epoch(uint32_t expected) {assert(expected==epoch);invalidations++;touch_capture_connection(false,connection_epoch+1);}
static void load(const uint8_t *bytes,size_t n) {assert(n<=sizeof(incoming));memcpy(incoming,bytes,n);incoming_pos=0;incoming_size=n;}
static void capture_setup(void) {
 touch_uart_rebind(false);xQueueReset(queue);epoch=connection_epoch=7;generation=5;capture=1;connected=linked=true;
 phase=TOUCH_RECORDING;strcpy(capture_id,"capture");total=sequence=0;started=last_pcm=last_keepalive=clock_ms=0;
 overflow=false;host_pcm=invalidations=0;noise=endless_events=short_write=false;publish();
}
int main(void) {
 assert(touch_capture_init()==ESP_OK);
 tc_frame_t source={.type=TC_PCM,.generation=5,.capture=1,.length=4,.payload={1,2,3,4}},frame;
 uint8_t wire[TC_WIRE_MAX];size_t n=tc_encode(&source,wire,sizeof(wire));assert(n);
 capture_setup();load(wire,n/2);assert(touch_uart_read(&frame)==0);
 load(wire+n/2,n-n/2);assert(touch_uart_read(&frame)==1 && frame.length==4 && !memcmp(frame.payload,source.payload,4));
 /* Error events must win over even fully buffered, otherwise valid PCM. */
 const int errors[]={UART_FIFO_OVF,UART_BUFFER_FULL,UART_FRAME_ERR,UART_PARITY_ERR};
 for(unsigned i=0;i<4;i++) {
  capture_setup();load(wire,n/2);assert(touch_uart_read(&frame)==0);
  load(wire,n);uart_event_t data={.type=UART_DATA},bad={.type=errors[i]};
  xQueueSend(events,&data,0);xQueueSend(events,&bad,0);xQueueSend(events,&data,0);
  unsigned before=flushes;touch_capture_worker_step();
  assert(invalidations==1 && !host_pcm && phase==TOUCH_UNAVAILABLE && flushes>before);
  tc_parser_t empty={0};assert(!memcmp(&parser,&empty,sizeof(parser)) && !((queue_t *)events)->count && incoming_pos==incoming_size);
  capture_setup();load(wire,n);touch_capture_worker_step();assert(host_pcm==1 && total==4 && !invalidations);
 }
 capture_setup();uint8_t broken[TC_WIRE_MAX];memcpy(broken,wire,n);broken[n-2]^=1;
 load(broken,n);touch_capture_worker_step();assert(invalidations && !host_pcm);
 capture_setup();load(wire,n/2);assert(touch_uart_read(&frame)==0);touch_uart_rebind(false);
 load(wire,n);assert(touch_uart_read(&frame)==1); /* explicit flush resets partial parser */
 noise=true;byte_reads=0;assert(touch_uart_read(&frame)==-1 && byte_reads<=TC_WIRE_MAX);
 byte_reads=0;assert(touch_uart_read(&frame)==0 && byte_reads==TC_WIRE_MAX);noise=false;touch_uart_rebind(false);
 endless_events=true;event_reads=0;assert(touch_uart_read(&frame)==0 && event_reads==20);endless_events=false;
 reset_levels=delay_ms=0;touch_uart_rebind(true);assert(reset_levels==1 && delay_ms==100);
 short_write=true;assert(!touch_uart_send(&(tc_frame_t){.type=TC_HELLO,.generation=9}));
 free(queue);free(events);return 0;
}
