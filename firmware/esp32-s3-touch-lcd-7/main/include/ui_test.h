#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Initialize the ESP-01 hardware bring-up and benchmark test scene.
 */
void ui_test_init(void);

/**
 * @brief Update the test scene with latest touch coordinates and frame timing.
 * @param touch_active True if display is currently being touched.
 * @param x Current X coordinate (0..1023)
 * @param y Current Y coordinate (0..599)
 * @param point_count Number of active touch points (0..5)
 * @param fps Current rendered frames per second
 */
void ui_test_update_touch(bool touch_active, uint16_t x, uint16_t y, uint8_t point_count, uint32_t fps);

#ifdef __cplusplus
}
#endif
