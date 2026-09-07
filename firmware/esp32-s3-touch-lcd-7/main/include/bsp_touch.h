#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint16_t x;
    uint16_t y;
    uint16_t size;
    uint8_t id;
} bsp_touch_point_t;

typedef struct {
    uint8_t point_count;
    bsp_touch_point_t points[5];
} bsp_touch_data_t;

/**
 * @brief Initialize the I2C bus and GT911 capacitive touch controller.
 * @return ESP_OK on success.
 */
esp_err_t bsp_touch_init(void);

/**
 * @brief Read touch data from the GT911 controller.
 * @param touch_data Output struct filled with touch count and points.
 * @return ESP_OK if valid data read, ESP_ERR_INVALID_STATE if no touch.
 */
esp_err_t bsp_touch_read(bsp_touch_data_t *touch_data);

/**
 * @brief Get the detected GT911 I2C address (0x5D or 0x14).
 */
uint8_t bsp_touch_get_i2c_addr(void);

#ifdef __cplusplus
}
#endif
