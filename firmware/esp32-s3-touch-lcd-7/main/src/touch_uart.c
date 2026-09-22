#include "touch_uart.h"
#include "board_config.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>
static tc_parser_t parser;
static QueueHandle_t events;
esp_err_t touch_uart_init(void) {
  gpio_config_t reset = {.pin_bit_mask = 1ULL << BOARD_C6_RESET,
                         .mode = GPIO_MODE_OUTPUT_OD,
                         .pull_up_en = GPIO_PULLUP_ENABLE};
  ESP_ERROR_CHECK(gpio_config(&reset));
  gpio_set_level(BOARD_C6_RESET, 1);
  uart_config_t c = {.baud_rate = 921600,
                     .data_bits = UART_DATA_8_BITS,
                     .parity = UART_PARITY_DISABLE,
                     .stop_bits = UART_STOP_BITS_1,
                     .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
                     .source_clk = UART_SCLK_DEFAULT};
  esp_err_t e = uart_driver_install(UART_NUM_1, 16 * 1050, 0, 20, &events, 0);
  if (e != ESP_OK)
    return e;
  e = uart_param_config(UART_NUM_1, &c);
  if (e != ESP_OK)
    return e;
  return uart_set_pin(UART_NUM_1, BOARD_C6_TX, BOARD_C6_RX, UART_PIN_NO_CHANGE,
                      UART_PIN_NO_CHANGE);
}
bool touch_uart_send(const tc_frame_t *f) {
  uint8_t wire[TC_WIRE_MAX];
  size_t n = tc_encode(f, wire, sizeof(wire));
  return n && uart_write_bytes(UART_NUM_1, wire, n) == (int)n &&
         uart_wait_tx_done(UART_NUM_1, pdMS_TO_TICKS(40)) == ESP_OK;
}
int touch_uart_read(tc_frame_t *f) {
  uart_event_t e;
  for (unsigned i = 0; i < 20 && xQueueReceive(events, &e, 0) == pdTRUE; i++)
    if (e.type == UART_FIFO_OVF || e.type == UART_BUFFER_FULL ||
        e.type == UART_FRAME_ERR || e.type == UART_PARITY_ERR) {
      touch_uart_rebind(false);
      return -1;
    }
  uint8_t byte;
  for (unsigned i = 0; i < TC_WIRE_MAX && uart_read_bytes(UART_NUM_1, &byte, 1, 0) == 1; i++) {
    int r = tc_feed(&parser, byte, f);
    if (r)
      return r;
  }
  return 0;
}
void touch_uart_rebind(bool reset) {
  uart_flush_input(UART_NUM_1);
  xQueueReset(events);
  memset(&parser, 0, sizeof(parser));
  if (reset) {
    gpio_set_level(BOARD_C6_RESET, 0);
    vTaskDelay(pdMS_TO_TICKS(100));
    gpio_set_level(BOARD_C6_RESET, 1);
  }
}
