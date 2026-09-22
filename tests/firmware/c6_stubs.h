#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <assert.h>
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERROR_CHECK(x) assert((x)==ESP_OK)
typedef int BaseType_t;
typedef void *QueueHandle_t;
#define pdTRUE 1
#define pdFALSE 0
#define pdMS_TO_TICKS(x) (x)
QueueHandle_t xQueueCreate(int, size_t);
int xQueueReceive(QueueHandle_t, void *, int);
int xQueueSendFromISR(QueueHandle_t,const void *,BaseType_t *);
void xQueueReset(QueueHandle_t);
void vTaskDelay(int);
int64_t esp_timer_get_time(void);
typedef struct { uint64_t pin_bit_mask; int mode; } gpio_config_t;
#define GPIO_MODE_OUTPUT 1
#define GPIO_NUM_0 0
#define GPIO_NUM_1 1
#define GPIO_NUM_2 2
#define GPIO_NUM_3 3
int gpio_config(const gpio_config_t *);
int gpio_set_level(int,int);
typedef void *i2s_chan_handle_t;
typedef struct {void *dma_buf;size_t size;} i2s_event_data_t;
typedef struct {int dma_desc_num,dma_frame_num;} i2s_chan_config_t;
#define I2S_CHANNEL_DEFAULT_CONFIG(a,b) ((i2s_chan_config_t){0})
#define I2S_STD_CLK_DEFAULT_CONFIG(a) (a)
#define I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(a,b) 0
#define I2S_GPIO_UNUSED -1
typedef struct {int clk_cfg,slot_cfg;struct{int mclk,bclk,ws,dout,din;} gpio_cfg;} i2s_std_config_t;
typedef struct {bool (*on_recv)(i2s_chan_handle_t,i2s_event_data_t *,void *);} i2s_event_callbacks_t;
int i2s_new_channel(const i2s_chan_config_t *,void *,i2s_chan_handle_t *);
int i2s_channel_init_std_mode(i2s_chan_handle_t,const i2s_std_config_t *);
int i2s_channel_register_event_callback(i2s_chan_handle_t,const i2s_event_callbacks_t *,void *);
int i2s_channel_enable(i2s_chan_handle_t);
int i2s_channel_disable(i2s_chan_handle_t);
int i2s_del_channel(i2s_chan_handle_t);
typedef struct {int type;} uart_event_t;
typedef struct {int baud_rate,data_bits,parity,stop_bits,flow_ctrl,source_clk;} uart_config_t;
#define UART_NUM_1 1
#define UART_DATA_8_BITS 8
#define UART_PARITY_DISABLE 0
#define UART_STOP_BITS_1 1
#define UART_HW_FLOWCTRL_DISABLE 0
#define UART_SCLK_DEFAULT 0
#define UART_PIN_NO_CHANGE -1
#define UART_FIFO_OVF 1
#define UART_BUFFER_FULL 2
#define UART_FRAME_ERR 3
#define UART_PARITY_ERR 4
int uart_driver_install(int,int,int,int,QueueHandle_t *,int);
int uart_param_config(int,const uart_config_t *);
int uart_set_pin(int,int,int,int,int);
int uart_write_bytes(int,const void *,size_t);
int uart_wait_tx_done(int,int);
int uart_flush_input(int);
int uart_read_bytes(int,void *,size_t,int);
