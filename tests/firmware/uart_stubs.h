#pragma once
#include "transport_stubs.h"
#define ESP_ERROR_CHECK(x) assert((x)==ESP_OK)
#define pdPASS 1
typedef void *QueueHandle_t;
QueueHandle_t xQueueCreate(int,size_t);
int xQueueSend(QueueHandle_t,const void *,int);
int xQueueReceive(QueueHandle_t,void *,int);
void xQueueReset(QueueHandle_t);
int xTaskCreate(void (*)(void *),const char *,int,void *,int,void *);
void vTaskDelay(int);
int64_t esp_timer_get_time(void);
uint32_t esp_random(void);
typedef struct {uint64_t pin_bit_mask;int mode,pull_up_en;} gpio_config_t;
#define GPIO_MODE_OUTPUT_OD 1
#define GPIO_PULLUP_ENABLE 1
int gpio_config(const gpio_config_t *);
int gpio_set_level(int,int);
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
#define UART_DATA 5
int uart_driver_install(int,int,int,int,QueueHandle_t *,int);
int uart_param_config(int,const uart_config_t *);
int uart_set_pin(int,int,int,int,int);
int uart_write_bytes(int,const void *,size_t);
int uart_wait_tx_done(int,int);
int uart_flush_input(int);
int uart_read_bytes(int,void *,size_t,int);
