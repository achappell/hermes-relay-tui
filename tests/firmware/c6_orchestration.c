#include <stdlib.h>
#include "main.c"
/* Execute the production callback, command handler and bounded worker. */
typedef struct {unsigned count,limit;size_t size;unsigned char data[16][sizeof(pcm_block_t)];} queue_t;
static uint64_t clock_ms;
static bool enabled, fail_init, fail_enable, fail_write;
static int disable_inject, disables, deletes;
static tc_frame_t sent[2048];static unsigned sent_count;
QueueHandle_t xQueueCreate(int n,size_t size) {queue_t *q=calloc(1,sizeof(*q));assert(n<=16 && size<=sizeof(pcm_block_t));q->limit=n;q->size=size;return q;}
int xQueueReceive(QueueHandle_t handle,void *data,int wait) {queue_t *q=handle;(void)wait;if(!q->count)return 0;memcpy(data,q->data[0],q->size);memmove(q->data,q->data+1,(--q->count)*sizeof(q->data[0]));return 1;}
int xQueueSendFromISR(QueueHandle_t handle,const void *data,BaseType_t *wake) {queue_t *q=handle;*wake=0;if(q->count==q->limit)return 0;memcpy(q->data[q->count++],data,q->size);return 1;}
void xQueueReset(QueueHandle_t handle) {((queue_t *)handle)->count=0;}
void vTaskDelay(int n) {clock_ms+=n;}
int64_t esp_timer_get_time(void) {return clock_ms*1000;}
int gpio_config(const gpio_config_t *c) {(void)c;return 0;}
int gpio_set_level(int p,int v) {(void)p;(void)v;return 0;}
int i2s_new_channel(const i2s_chan_config_t *c,void *tx,i2s_chan_handle_t *h) {assert(c->dma_desc_num==8 && c->dma_frame_num==256);(void)tx;*h=(void *)1;return 0;}
int i2s_channel_init_std_mode(i2s_chan_handle_t h,const i2s_std_config_t *c) {(void)h;(void)c;return fail_init?-1:0;}
int i2s_channel_register_event_callback(i2s_chan_handle_t h,const i2s_event_callbacks_t *c,void *p) {(void)h;(void)p;assert(c->on_recv==receive_cb);return 0;}
int i2s_channel_enable(i2s_chan_handle_t h) {(void)h;if(fail_enable)return -1;enabled=true;return 0;}
static void block(uint32_t sample) {uint32_t raw[512];for(unsigned i=0;i<512;i+=2){raw[i]=sample;raw[i+1]=0;}i2s_event_data_t event={.dma_buf=raw,.size=sizeof(raw)};assert(enabled);receive_cb(rx,&event,NULL);}
int i2s_channel_disable(i2s_chan_handle_t h) {(void)h;assert(enabled);disables++;while(disable_inject>0){disable_inject--;block(0x34560000);}enabled=false;return 0;}
int i2s_del_channel(i2s_chan_handle_t h) {(void)h;assert(!enabled);deletes++;return 0;}
int uart_driver_install(int a,int b,int c,int d,QueueHandle_t *q,int e) {(void)a;(void)b;(void)c;(void)d;(void)e;*q=xQueueCreate(16,sizeof(uart_event_t));return 0;}
int uart_param_config(int a,const uart_config_t *c) {(void)a;(void)c;return 0;}
int uart_set_pin(int a,int b,int c,int d,int e) {(void)a;(void)b;(void)c;(void)d;(void)e;return 0;}
int uart_write_bytes(int port,const void *wire,size_t n) {(void)port;assert(sent_count<2048);assert(tc_decode(wire,n-1,&sent[sent_count++]));return fail_write?-1:(int)n;}
int uart_wait_tx_done(int a,int b) {(void)a;(void)b;return 0;}
int uart_flush_input(int a) {(void)a;return 0;}
int uart_read_bytes(int a,void *b,size_t c,int d) {(void)a;(void)b;(void)c;(void)d;return 0;}
static void setup(uint64_t time) {
 stop_rx();xQueueReset(pcm_queue);xQueueReset(uart_events);state=(tc_state_t){0};clock_ms=time;
 sent_count=disables=deletes=disable_inject=0;fail_init=fail_enable=fail_write=false;
 command(&(tc_frame_t){.type=TC_HELLO,.generation=7});assert(sent_count==1 && sent[0].type==TC_READY);
 command(&(tc_frame_t){.type=TC_START,.generation=7,.capture=1});assert(enabled && state.phase==TC_STARTING);
}
static void settle(void) {
 for(int i=0;i<16;i++){clock_ms+=16;block(0);worker_step();}
 assert(state.phase==TC_CAPTURING && sent_count==2 && sent[1].type==TC_STARTED);
}
static void end_command(void) {command(&(tc_frame_t){.type=TC_END,.generation=7,.capture=1});}
static void keepalive(void) {command(&(tc_frame_t){.type=TC_KEEPALIVE,.generation=7,.capture=1});}
int main(void) {
 pcm_queue=xQueueCreate(16,sizeof(pcm_block_t));uart_events=xQueueCreate(16,sizeof(uart_event_t));
 setup(0);settle();
 block(0x12340000);block(0x23450000);disable_inject=1;end_command();assert(!enabled && state.phase==TC_DRAINING);
 for(int i=0;i<4;i++)worker_step();
 assert(sent_count==6 && sent[5].type==TC_ENDED && sent[5].sequence==3 && tc_u32(sent[5].payload)==1536);
 for(unsigned i=0;i<3;i++){assert(sent[i+2].type==TC_PCM && sent[i+2].sequence==i);assert(sent[i+2].payload[1]==0x12+i*0x11);}
 end_command();assert(sent_count==7 && sent[6].type==TC_ENDED); /* cached terminal */
 setup(0);settle();for(int i=0;i<16;i++)block(0);disable_inject=1;end_command();
 assert(!enabled && sent_count==3 && sent[2].type==TC_ERROR && sent[2].payload[0]==TC_OVERFLOW);
 assert(((queue_t *)pcm_queue)->count==0);worker_step();assert(sent_count==3);
 setup(0);settle();block(0);command(&(tc_frame_t){.type=TC_ABORT,.generation=7,.capture=1,.length=1,.payload={TC_CANCELLED}});worker_step();assert(!enabled && sent_count==2 && !((queue_t *)pcm_queue)->count);
 setup(0);clock_ms=1000;worker_step();assert(!enabled && sent[sent_count-1].payload[0]==TC_TIMEOUT);
 setup(0);settle();block(0);end_command();clock_ms=1000;worker_step();assert(sent[sent_count-1].type==TC_ERROR); /* expired drain lease */
 setup(0);settle();block(0);fail_write=true;worker_step();assert(!enabled && !((queue_t *)pcm_queue)->count);
 setup(0);settle();for(int i=0;i<17;i++)block(0);worker_step();assert(!enabled && sent[sent_count-1].payload[0]==TC_OVERFLOW);
 setup(0);settle();for(int i=0;i<938;i++){clock_ms+=15;keepalive();block(0x7fff0000);worker_step();}
 while(state.phase==TC_DRAINING) {
  worker_step();
 }
 assert(state.ended && state.bytes==480000 && sent[sent_count-1].type==TC_ENDED);
 setup((1ULL<<32)-128);settle();assert(state.started==clock_ms);block(0);worker_step();assert(state.phase==TC_CAPTURING); /* millisecond wrap */
 setup(0);settle();block(0);block(0);block(0);clock_ms=15256;keepalive();worker_step();assert(state.phase==TC_DRAINING);
 uint64_t expiry=drain_deadline;end_command();assert(state.phase==TC_DRAINING && drain_deadline==expiry);
 worker_step();worker_step();worker_step();assert(state.ended && state.bytes==1536 && sent_count==6 && sent[5].type==TC_ENDED);
 setup(0);stop_rx();tc_abort(&state);int before=disables;fail_init=true;
 command(&(tc_frame_t){.type=TC_START,.generation=7,.capture=2});assert(!rx && disables==before && !enabled);
 fail_init=false;fail_enable=true;command(&(tc_frame_t){.type=TC_START,.generation=7,.capture=3});assert(!rx && disables==before && !enabled);
 free(pcm_queue);free(uart_events);return 0;
}
