/* The sole Touch sender. LVGL and WebSocket callbacks only enqueue controls. */
#include "touch_capture.h"
#include "cJSON.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "touch_uart.h"
#include "ui_transport.h"
#include <stdio.h>
#include <string.h>
typedef struct {
  uint32_t epoch, capture;
  int kind;
  touch_phase_t requested_phase;
  char id[129];
  char outcome[16];
  bool capability;
} input_t;
static QueueHandle_t queue;
static touch_phase_t phase = TOUCH_UNAVAILABLE;
/* Only this small published view crosses tasks. Worker state below is private. */
static portMUX_TYPE view_lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t connection_epoch, overflow_epoch;
static touch_phase_t view_phase = TOUCH_UNAVAILABLE;
static uint32_t view_capture, view_epoch;
static const char *view_reason;
static bool connected, overflow;
static uint32_t epoch, generation, capture, sequence, total;
static uint64_t deadline, last_pcm, last_keepalive, started, last_hello;
static bool linked, reset_attempted;
static char capture_id[65], failed_audio[129];
static const char *unavailable_reason;
static bool current(void) {
  portENTER_CRITICAL(&view_lock);
  bool value = connected && epoch == connection_epoch;
  portEXIT_CRITICAL(&view_lock);
  return value;
}
static void publish(void) {
  portENTER_CRITICAL(&view_lock);
  view_phase = connected && epoch == connection_epoch ? phase : TOUCH_UNAVAILABLE;
  view_capture = capture; view_epoch = epoch;
  view_reason = unavailable_reason;
  portEXIT_CRITICAL(&view_lock);
}
static uint64_t now(void) { return esp_timer_get_time() / 1000; }
static bool uart_control(uint8_t type, uint8_t reason) {
  tc_frame_t f = {.type = type,
                  .generation = generation,
                  .capture = type == TC_HELLO ? 0 : capture,
                  .length = (type == TC_ABORT) ? 1 : 0};
  f.payload[0] = reason;
  return touch_uart_send(&f);
}
static bool host_control(const char *type) {
  char json[180];
  snprintf(json, sizeof(json),
           "{\"schema\":1,\"type\":\"%s\",\"capture_id\":\"%s\"}", type,
           capture_id);
  return current() && ui_transport_send_text_epoch(json, epoch) == ESP_OK;
}
static void fail(void) {
  if (capture && linked)
    uart_control(TC_ABORT, TC_TRANSPORT_LOST);
  phase = TOUCH_UNAVAILABLE;
  linked = false;
  capture_id[0] = 0;
  touch_uart_rebind(false);
  xQueueReset(queue);
  ui_transport_invalidate_epoch(epoch);
}
static void bind_link(bool reset) {
  touch_uart_rebind(reset);
  uint32_t previous_generation = generation;
  generation = esp_random();
  if (!generation || generation == previous_generation) {
    generation = previous_generation + 1;
    if (!generation) generation = 1;
  }
  capture = 0;
  linked = false;
  phase = TOUCH_UNAVAILABLE;
  deadline = now() + 1000;
  last_hello = now();
  if (!uart_control(TC_HELLO, 0))
    fail();
}
static void input(const input_t *e) {
  if (e->epoch != epoch || !current())
    return;
  if (e->kind >= 1 && e->kind <= 2 && e->requested_phase != phase)
    return;
  if (e->kind >= 2 && e->kind <= 3 && e->capture != capture)
    return;
  if (e->kind == 99) { fail(); return; }
  if (e->kind == TOUCH_TALK + 1 && phase == TOUCH_IDLE && linked) {
    if (capture == UINT32_MAX) {
      fail();
      return;
    }
    unavailable_reason = NULL;
    capture++;
    snprintf(capture_id, sizeof(capture_id), "%08lx-%08lx",
             (unsigned long)epoch, (unsigned long)capture);
    phase = TOUCH_ADMISSION;
    deadline = now() + 25000;
    sequence = total = 0;
    failed_audio[0] = 0;
    if (!host_control("mic_start"))
      fail();
  } else if (e->kind == TOUCH_FINISH + 1 && phase == TOUCH_RECORDING) {
    phase = TOUCH_DRAINING;
    deadline = now() + 1000;
    if (!uart_control(TC_END, 0))
      fail();
  } else if (e->kind == TOUCH_CANCEL + 1 &&
             (phase == TOUCH_ADMISSION || phase == TOUCH_STARTING ||
              phase == TOUCH_RECORDING)) {
    if (phase == TOUCH_ADMISSION) {
      fail();
      return;
    }
    phase = TOUCH_ABORTING;
    deadline = now() + 2000;
    uart_control(TC_ABORT, TC_CANCELLED);
    touch_uart_rebind(false);
    if (!host_control("mic_abort"))
      fail();
  } else if (e->kind == 10 && phase == TOUCH_ADMISSION &&
             !strcmp(e->id, capture_id)) {
    if (!e->capability) {
      unavailable_reason = "Incompatible host";
      fail();
      return;
    }
    phase = TOUCH_STARTING;
    deadline = now() + 2000;
    last_keepalive = now();
    if (!uart_control(TC_START, 0))
      fail();
  } else if (e->kind == 11 && phase == TOUCH_ADMISSION &&
             !strcmp(e->id, capture_id)) {
    unavailable_reason = "Not admitted by Home";
    fail();
  } else if (e->kind == 12 && capture_id[0] && !strcmp(e->id, capture_id)) {
    uart_control(TC_ABORT, TC_CANCELLED);
    touch_uart_rebind(false);
    capture_id[0] = 0;
    if (!strcmp(e->outcome, "error"))
      fail();
    else
      phase = linked ? TOUCH_IDLE : TOUCH_UNAVAILABLE;
  } else if (e->kind == 13 && strcmp(e->id, failed_audio)) {
    /* ID is serialized by cJSON below, never interpolated from untrusted JSON.
     */
    cJSON *o = cJSON_CreateObject();
    if (!o) {
      fail();
      return;
    }
    if (!cJSON_AddNumberToObject(o, "schema", 1) ||
        !cJSON_AddStringToObject(o, "type", "audio_playback_failed") ||
        !cJSON_AddStringToObject(o, "turn_id", e->id) ||
        !cJSON_AddStringToObject(o, "reason", "unsupported")) {
      cJSON_Delete(o);
      fail();
      return;
    }
    char *wire = cJSON_PrintUnformatted(o);
    cJSON_Delete(o);
    if (!wire || ui_transport_send_text_epoch(wire, epoch) != ESP_OK)
      fail();
    else
      snprintf(failed_audio, sizeof(failed_audio), "%s", e->id);
    cJSON_free(wire);
  }
}
static void uart_frame(const tc_frame_t *f) {
  if (f->generation != generation || !current())
    return;
  if (f->type == TC_READY && !linked && !f->capture) {
    linked = true;
    phase = TOUCH_IDLE;
    return;
  }
  if (f->capture != capture || !capture_id[0])
    return;
  if (f->type == TC_STARTED && phase == TOUCH_STARTING) {
    if (!host_control("mic_capture_started")) {
      fail();
      return;
    }
    phase = TOUCH_RECORDING;
    started = last_pcm = now();
  } else if (f->type == TC_PCM &&
             (phase == TOUCH_RECORDING || phase == TOUCH_DRAINING)) {
    if (f->sequence != sequence || f->length > TC_BYTES_MAX - total ||
        now() - started > 17000) {
      fail();
      return;
    }
    if (ui_transport_send_pcm_epoch(f->payload, f->length, epoch) != ESP_OK) {
      fail();
      return;
    }
    /* Sending may block, but never let a slow connection consume the lease or
     * accumulate an unbounded backlog. A 1024-byte frame represents 32 ms. */
    if (!current() || now() - last_pcm >= 250) { fail(); return; }
    sequence++;
    total += f->length;
    last_pcm = now();
  } else if (f->type == TC_ENDED &&
             (phase == TOUCH_RECORDING || phase == TOUCH_DRAINING)) {
    if (f->sequence != sequence || tc_u32(f->payload) != total) {
      fail();
      return;
    }
    phase = TOUCH_WORKING;
    if (!host_control("mic_end"))
      fail();
  } else if (f->type == TC_ERROR || f->type == TC_ABORT ||
             (f->type == TC_STARTED && phase != TOUCH_ABORTING) ||
             (f->type == TC_PCM && phase != TOUCH_ABORTING))
    fail();
}
static void service_deadlines(void) {
  uint64_t t = now();
  if (!linked && phase == TOUCH_UNAVAILABLE) {
    if (t >= deadline) {
      if (!reset_attempted) { reset_attempted = true; bind_link(true); }
      else deadline = UINT64_MAX;
    } else if (deadline != UINT64_MAX && t - last_hello >= 200) {
      last_hello = t;
      if (!uart_control(TC_HELLO, 0)) fail();
    }
  }
  if ((phase == TOUCH_ADMISSION || phase == TOUCH_STARTING ||
       phase == TOUCH_DRAINING || phase == TOUCH_ABORTING) && t >= deadline) {
    fail(); return;
  }
  if (phase == TOUCH_RECORDING &&
      (t - started >= TC_DURATION_MS || total == TC_BYTES_MAX)) {
    phase = TOUCH_DRAINING; deadline = t + 1000;
    if (!uart_control(TC_END, 0)) { fail(); return; }
  }
  if (phase == TOUCH_RECORDING && t - last_pcm >= 1000) { fail(); return; }
  if ((phase == TOUCH_STARTING || phase == TOUCH_RECORDING || phase == TOUCH_DRAINING) &&
      t - last_keepalive >= 250) {
    last_keepalive = t;
    if (!uart_control(TC_KEEPALIVE, 0)) fail();
  }
}
/* Deliberately bounded: controls and lease run between every UART/host send. */
void touch_capture_worker_step(void) {
  portENTER_CRITICAL(&view_lock);
  uint32_t latest_epoch = connection_epoch;
  bool online = connected;
  bool full = overflow && overflow_epoch == latest_epoch;
  overflow = false;
  portEXIT_CRITICAL(&view_lock);
  if (latest_epoch != epoch) {
    if (capture_id[0]) uart_control(TC_ABORT, TC_TRANSPORT_LOST);
    epoch = latest_epoch; capture_id[0] = 0;
    xQueueReset(queue);
    phase = TOUCH_UNAVAILABLE; linked = false; reset_attempted = false;
    if (online) bind_link(false);
  }
  if (full) fail();
  if (current()) {
    input_t e;
    service_deadlines();
    if (current() && xQueueReceive(queue, &e, 0) == pdTRUE) input(&e);
    if (current()) service_deadlines();
    if (current()) {
      tc_frame_t frame;
      int r = touch_uart_read(&frame);
      if (r > 0) uart_frame(&frame);
      else if (r < 0 && (phase == TOUCH_STARTING || phase == TOUCH_RECORDING || phase == TOUCH_DRAINING)) fail();
    }
    if (current()) service_deadlines();
  }
  publish();
}
static void worker(void *arg) {
  (void)arg;
  while (true) {
    touch_capture_worker_step();
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}
esp_err_t touch_capture_init(void) {
  esp_err_t e = touch_uart_init();
  if (e != ESP_OK)
    return e;
  queue = xQueueCreate(16, sizeof(input_t));
  if (!queue)
    return ESP_ERR_NO_MEM;
  return xTaskCreate(worker, "touch_capture", 8192, NULL, 6, NULL) == pdPASS
             ? ESP_OK
             : ESP_ERR_NO_MEM;
}
void touch_capture_connection(bool value, uint32_t value_epoch) {
  portENTER_CRITICAL(&view_lock);
  if ((int32_t)(value_epoch - connection_epoch) < 0) {
    portEXIT_CRITICAL(&view_lock); return;
  }
  connected = value;
  connection_epoch = value_epoch;
  /* Disable visible controls immediately; worker will publish the new link. */
  view_phase = TOUCH_UNAVAILABLE;
  view_epoch = value_epoch;
  portEXIT_CRITICAL(&view_lock);
}
static void enqueue(const input_t *e) {
  if (xQueueSend(queue, e, 0) != pdTRUE) {
    portENTER_CRITICAL(&view_lock);
    if (e->epoch == connection_epoch) { overflow = true; overflow_epoch = e->epoch; }
    portEXIT_CRITICAL(&view_lock);
  }
}
void touch_capture_command(touch_command_t command) {
  if (!queue) return;
  portENTER_CRITICAL(&view_lock);
  input_t e = {.epoch = view_epoch, .capture = view_capture,
               .kind = command + 1, .requested_phase = view_phase};
  portEXIT_CRITICAL(&view_lock);
  enqueue(&e);
}
touch_phase_t touch_capture_phase(void) {
  portENTER_CRITICAL(&view_lock);
  touch_phase_t value = view_phase;
  portEXIT_CRITICAL(&view_lock);
  return value;
}
void touch_capture_control(const char *json, uint32_t value_epoch) {
  if (!queue)
    return;
  cJSON *o = cJSON_Parse(json);
  if (!o) {
    input_t bad = {.epoch = value_epoch, .kind = 99}; enqueue(&bad);
    return;
  }
  input_t e = {.epoch = value_epoch};
  const cJSON *type = cJSON_GetObjectItem(o, "type"),
              *schema = cJSON_GetObjectItem(o, "schema");
  if (!cJSON_IsString(type) || !cJSON_IsNumber(schema) ||
      schema->valuedouble != 1) {
    cJSON_Delete(o);
    input_t bad = {.epoch = value_epoch, .kind = 99}; enqueue(&bad);
    return;
  }
  const char *id_key = "capture_id";
  if (!strcmp(type->valuestring, "mic_ready")) {
    e.kind = 10;
    e.capability = cJSON_IsTrue(cJSON_GetObjectItem(o, "capture_terminal"));
  } else if (!strcmp(type->valuestring, "mic_reject"))
    e.kind = 11;
  else if (!strcmp(type->valuestring, "mic_terminal")) {
    e.kind = 12;
    cJSON *v = cJSON_GetObjectItem(o, "outcome");
    if (cJSON_IsString(v))
      snprintf(e.outcome, sizeof(e.outcome), "%s", v->valuestring);
    if (strcmp(e.outcome, "complete") && strcmp(e.outcome, "no_turn") &&
        strcmp(e.outcome, "error")) {
      cJSON_Delete(o);
      e.kind = 99; enqueue(&e);
      return;
    }
  } else if (!strcmp(type->valuestring, "audio_start")) {
    e.kind = 13;
    id_key = "turn_id";
  }
  cJSON *id = cJSON_GetObjectItem(o, id_key);
  if (e.kind) {
    size_t limit = e.kind == 13 ? 128 : 64;
    if (!cJSON_IsString(id) || !id->valuestring[0] || strlen(id->valuestring) > limit)
      e.kind = 99;
    else snprintf(e.id, sizeof(e.id), "%s", id->valuestring);
    enqueue(&e);
  }
  cJSON_Delete(o);
}

const char *touch_capture_status(void) {
  static const char *names[] = {"Voice unavailable", "Ready to talk",
                                "Checking Home",     "Starting microphone",
                                "Listening",         "Finishing",
                                "Working",           "Cancelling"};
  portENTER_CRITICAL(&view_lock);
  const char *value = view_reason && (view_phase == TOUCH_IDLE || view_phase == TOUCH_UNAVAILABLE)
      ? view_reason : names[view_phase];
  portEXIT_CRITICAL(&view_lock);
  return value;
}
