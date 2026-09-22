#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
typedef enum { TOUCH_UNAVAILABLE, TOUCH_IDLE, TOUCH_ADMISSION, TOUCH_STARTING, TOUCH_RECORDING, TOUCH_DRAINING, TOUCH_WORKING, TOUCH_ABORTING } touch_phase_t;
typedef enum { TOUCH_TALK, TOUCH_FINISH, TOUCH_CANCEL } touch_command_t;
esp_err_t touch_capture_init(void);
void touch_capture_connection(bool connected,uint32_t epoch);
void touch_capture_control(const char *json,uint32_t epoch);
void touch_capture_command(touch_command_t command);
touch_phase_t touch_capture_phase(void);

const char *touch_capture_status(void);

/* Deterministic bounded worker iteration; production task invokes this. */
void touch_capture_worker_step(void);
