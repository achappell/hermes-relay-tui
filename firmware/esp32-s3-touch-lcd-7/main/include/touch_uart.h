#pragma once
#include "capture_protocol.h"
#include "esp_err.h"
esp_err_t touch_uart_init(void);
bool touch_uart_send(const tc_frame_t *frame);
/* frame=1, no frame=0, transport/parser failure=-1 */
int touch_uart_read(tc_frame_t *frame);
void touch_uart_rebind(bool reset);
