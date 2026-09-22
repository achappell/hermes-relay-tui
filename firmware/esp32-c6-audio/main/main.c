/* One bounded worker owns I2S, UART and state: no unordered PCM producers. */
#include "capture_state.h"
#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include "driver/uart.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>
#include <stdatomic.h>
#include "freertos/queue.h"
static tc_state_t state;
static tc_parser_t parser;
static i2s_chan_handle_t rx;
static QueueHandle_t uart_events;
/* Completed DMA is copied into owned storage before IDF can reuse it. The
 * driver's read queue is deliberately unused; its overflow only drops duplicate
 * DMA pointers, not our samples. Only owned-queue overflow invalidates capture. */
typedef struct { uint16_t size; uint8_t pcm[512]; } pcm_block_t;
static QueueHandle_t pcm_queue;
static atomic_bool dma_overflow, settled, sample_limit;
static bool rx_running;
static uint32_t settle_frames, sampled_bytes;
static atomic_uint sample_started;
static uint64_t last_pcm, drain_deadline;
static uint64_t now_ms(void) { return esp_timer_get_time() / 1000; }
static bool receive_cb(i2s_chan_handle_t h, i2s_event_data_t *e, void *ctx) {
  (void)h; (void)ctx;
  if (!e->dma_buf || e->size != 2048) {
    atomic_store(&dma_overflow, true);
    return false;
  }
  if (settle_frames) {
    settle_frames -= 256;
    if (!settle_frames) {
      atomic_store(&sample_started, (uint32_t)now_ms());
      atomic_store(&settled, true);
    }
    return false;
  }
  if (atomic_load(&sample_limit) || atomic_load(&dma_overflow)) return false;
  /* A block completed at the boundary belongs to the bounded utterance. */
  if ((uint32_t)now_ms() - atomic_load(&sample_started) > TC_DURATION_MS) {
    atomic_store(&sample_limit, true);
    return false;
  }
  static pcm_block_t block;
  block.size = 512;
  if (block.size > TC_BYTES_MAX - sampled_bytes)
    block.size = TC_BYTES_MAX - sampled_bytes;
  const uint32_t *samples = e->dma_buf;
  for (size_t i = 0; i < block.size / 2; i++)
    tc_pcm16(samples[i * 2], block.pcm + i * 2);
  BaseType_t wake = pdFALSE;
  if (xQueueSendFromISR(pcm_queue, &block, &wake) != pdTRUE)
    atomic_store(&dma_overflow, true);
  else sampled_bytes += block.size;
  if (sampled_bytes == TC_BYTES_MAX) atomic_store(&sample_limit, true);
  return wake == pdTRUE;
}
static bool stop_rx(void) {
  if (rx_running) {
    if (i2s_channel_disable(rx) != ESP_OK) return false;
    rx_running = false;
  }
  if (rx) {
    if (i2s_del_channel(rx) != ESP_OK) return false;
    rx = NULL;
  }
  return true;
}
static bool send_frame(uint8_t type, uint32_t seq, const uint8_t *payload,
                       uint16_t len) {
  static tc_frame_t f;
  f = (tc_frame_t){.type = type,
                  .generation = state.generation,
                  .capture = type == TC_READY ? 0 : state.capture,
                  .sequence = seq,
                  .length = len};
  if (len)
    memcpy(f.payload, payload, len);
  static uint8_t wire[TC_WIRE_MAX];
  size_t n = tc_encode(&f, wire, sizeof(wire));
  return n && uart_write_bytes(UART_NUM_1, wire, n) == (int)n &&
         uart_wait_tx_done(UART_NUM_1, pdMS_TO_TICKS(40)) == ESP_OK;
}
static void abort_capture(uint8_t reason) {
  stop_rx();
  xQueueReset(pcm_queue);
  tc_abort(&state);
  send_frame(TC_ERROR, 0, &reason, 1);
}
static bool start_rx(void) {
  if (rx && !stop_rx()) return false;
  xQueueReset(pcm_queue);
  atomic_store(&dma_overflow, false);
  atomic_store(&settled, false);
  atomic_store(&sample_limit, false);
  sampled_bytes = 0;
  settle_frames = 4096;
  i2s_chan_config_t channel =
      I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  channel.dma_desc_num = 8;
  channel.dma_frame_num = 256;
  if (i2s_new_channel(&channel, NULL, &rx) != ESP_OK)
    return false;
  i2s_std_config_t cfg = {.clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(16000),
                          .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
                              I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
                          .gpio_cfg = {.mclk = I2S_GPIO_UNUSED,
                                       .bclk = GPIO_NUM_0,
                                       .ws = GPIO_NUM_1,
                                       .dout = I2S_GPIO_UNUSED,
                                       .din = GPIO_NUM_2}};
  i2s_event_callbacks_t callbacks = {.on_recv = receive_cb};
  if (i2s_channel_init_std_mode(rx, &cfg) != ESP_OK ||
      i2s_channel_register_event_callback(rx, &callbacks, NULL) != ESP_OK ||
      i2s_channel_enable(rx) != ESP_OK) {
    stop_rx();
    return false;
  }
  rx_running = true;
  /* Unknown microphone power history: callback discards initial 2^18 clocks. */
  last_pcm = now_ms();
  return true;
}
static void finish(void) {
  /* Disable first: callbacks may complete or overflow during this operation.
   * Never read IDF after disable; its cursor has been reset. */
  if (!stop_rx()) { abort_capture(TC_I2S_FAILURE); return; }
  if (atomic_load(&dma_overflow)) { abort_capture(TC_OVERFLOW); return; }
  state.phase = TC_DRAINING;
  drain_deadline = now_ms() + 1000;
}
static void ended(void) {
  uint8_t total[4];
  tc_put_u32(total, state.bytes);
  if (send_frame(TC_ENDED, state.sequence, total, 4)) tc_ended(&state);
  else abort_capture(TC_TRANSPORT_LOST);
}
static void command(const tc_frame_t *f) {
  if (f->type == TC_HELLO && f->generation != state.generation) {
    if (!stop_rx()) { abort_capture(TC_I2S_FAILURE); return; }
    xQueueReset(pcm_queue);
    uart_flush_input(UART_NUM_1);
    memset(&parser, 0, sizeof(parser));
  }
  int result = tc_command(&state, f, now_ms());
  if (result < 0) {
    abort_capture(TC_MALFORMED);
    return;
  }
  if (!result)
    return;
  if (result == 2) { ended(); return; }
  if (f->type == TC_HELLO) {
    if (!send_frame(TC_READY, 0, NULL, 0))
      tc_abort(&state);
  } else if (f->type == TC_START) {
    if (!start_rx())
      abort_capture(TC_I2S_FAILURE);
  } else if (f->type == TC_ABORT) {
    stop_rx();
    xQueueReset(pcm_queue);
  }
  else if (f->type == TC_END)
    finish();
}
/* One deterministic iteration: controls/lease before each bounded PCM send. */
static void worker_step(void) {
  uart_event_t ev;
  bool uart_bad = false;
  for (int i = 0; i < 16 && xQueueReceive(uart_events, &ev, 0) == pdTRUE; i++)
    if (ev.type == UART_FIFO_OVF || ev.type == UART_BUFFER_FULL ||
        ev.type == UART_FRAME_ERR || ev.type == UART_PARITY_ERR) uart_bad = true;
  if (uart_bad) {
    uart_flush_input(UART_NUM_1);
    memset(&parser, 0, sizeof(parser));
    if (state.phase >= TC_STARTING) abort_capture(TC_OVERFLOW);
  }
  uint8_t incoming[128];
  static tc_frame_t frame;
  int n = uart_read_bytes(UART_NUM_1, incoming, sizeof(incoming), 0);
  for (int i = 0; i < n; i++) {
    int r = tc_feed(&parser, incoming[i], &frame);
    if (r == 1) command(&frame);
    else if (r < 0 && state.phase >= TC_STARTING) abort_capture(TC_MALFORMED);
  }
  if (state.phase == TC_IDLE || state.phase == TC_UNBOUND) return;
  int tick = tc_tick(&state, now_ms());
  if (tick < 0) { abort_capture(TC_TIMEOUT); return; }
  if (atomic_load(&dma_overflow)) { abort_capture(TC_OVERFLOW); return; }
  if (state.phase == TC_STARTING) {
    if (atomic_load(&settled)) {
      if (!tc_started(&state, now_ms()) || !send_frame(TC_STARTED, 0, NULL, 0)) {
        abort_capture(TC_TIMEOUT); return;
      }
      uint64_t current = now_ms();
      state.started = current - ((uint32_t)current - atomic_load(&sample_started));
      last_pcm = now_ms();
    } else if (now_ms() - last_pcm >= 1000) abort_capture(TC_TIMEOUT);
    return;
  }
  if (tick > 0 || (state.phase == TC_CAPTURING && atomic_load(&sample_limit))) finish();
  if (state.phase != TC_CAPTURING && state.phase != TC_DRAINING) return;
  if (state.phase == TC_DRAINING && now_ms() >= drain_deadline) {
    abort_capture(TC_TIMEOUT); return;
  }
  static pcm_block_t block;
  if (xQueueReceive(pcm_queue, &block, 0) == pdTRUE) {
    uint32_t sequence = state.sequence;
    if (!tc_accept_pcm(&state, block.size) ||
        !send_frame(TC_PCM, sequence, block.pcm, block.size)) {
      abort_capture(TC_TRANSPORT_LOST); return;
    }
    last_pcm = now_ms();
  } else if (state.phase == TC_DRAINING) {
    if (atomic_load(&dma_overflow)) abort_capture(TC_OVERFLOW);
    else ended();
  } else if (now_ms() - last_pcm >= 1000) abort_capture(TC_TIMEOUT);
}
void app_main(void) {
  pcm_queue = xQueueCreate(16, sizeof(pcm_block_t));
  if (!pcm_queue) return;
  gpio_config_t amp = {.pin_bit_mask = 1ULL << 3, .mode = GPIO_MODE_OUTPUT};
  ESP_ERROR_CHECK(gpio_config(&amp));
  gpio_set_level(GPIO_NUM_3, 0);
  uart_config_t uart = {.baud_rate = 921600,
                        .data_bits = UART_DATA_8_BITS,
                        .parity = UART_PARITY_DISABLE,
                        .stop_bits = UART_STOP_BITS_1,
                        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
                        .source_clk = UART_SCLK_DEFAULT};
  ESP_ERROR_CHECK(
      uart_driver_install(UART_NUM_1, 4096, 0, 16, &uart_events, 0));
  ESP_ERROR_CHECK(uart_param_config(UART_NUM_1, &uart));
  ESP_ERROR_CHECK(
      uart_set_pin(UART_NUM_1, 18, 19, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
  while (true) {
    worker_step();
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}
