#pragma once
#include <unistd.h>

#define pdMS_TO_TICKS(ms) (ms)
#define portMAX_DELAY 0xFFFFFFFFUL

static inline void vTaskDelay(uint32_t ms) {
    usleep(ms * 1000);
}
